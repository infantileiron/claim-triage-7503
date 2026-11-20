import os,json
import redis
from fastapi import APIRouter,Depends,HTTPException,Response
from sqlalchemy.exc import IntegrityError
from src.config.database import db
from src.models.entities import User,Claim,Training,Review,Audit,DpRequest
from src.schemas.business import Login,ClaimInput,TrainingInput,ReviewInput,DpQueryInput
from src.middlewares.auth import current,editor,admin
from src.utils.security import verify,token
from src.services.business import audit,dump
from src.services import privacy
from src.controllers.business import ensure_training
router=APIRouter()
@router.post('/auth/login')
def login(data:Login,s=Depends(db)):
 u=s.query(User).filter_by(email=data.email).first()
 if not u or not verify(data.password,u.password):raise HTTPException(401,'账号或密码错误')
 return {'token':token(u),'user':dump(u)}
@router.get('/me')
def me(u=Depends(current)):return dump(u)
@router.get('/claims')
def claims(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Claim).order_by(Claim.id).all()]
@router.post('/claims')
def create_claim(data:ClaimInput,u=Depends(editor),s=Depends(db)):
 r=Claim(**data.model_dump());s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'报销编号重复')
 audit(s,u,'录入报销 '+r.code);return dump(r)
@router.put('/claims/{i}')
def edit_claim(i:int,data:ClaimInput,u=Depends(editor),s=Depends(db)):
 r=s.get(Claim,i)
 if not r:raise HTTPException(404,'报销样本不存在')
 for k,v in data.model_dump().items():setattr(r,k,v)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'报销编号重复')
 audit(s,u,'修订报销 '+str(i));return dump(r)
@router.get('/trainings')
def trainings(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Training).order_by(Training.id.desc()).all()]
@router.post('/trainings')
def train(data:TrainingInput,u=Depends(editor),s=Depends(db)):
 rows=[dump(r) for r in s.query(Claim).order_by(Claim.id).all()];r=Training(**data.model_dump(),result={'snapshot':rows});s.add(r);s.commit()
 try:redis.Redis.from_url(os.environ['REDIS_URL']).rpush('claim:trainings',r.id)
 except redis.RedisError:r.state='failed';r.error='队列暂不可用，请稍后重新提交';s.commit();raise HTTPException(503,r.error)
 audit(s,u,'提交训练 '+str(r.id));return dump(r)
@router.get('/trainings/{i}')
def detail(i:int,u=Depends(current),s=Depends(db)):return dump(ensure_training(s,i))
@router.get('/trainings/{i}/export')
def export(i:int,u=Depends(current),s=Depends(db)):
 r=ensure_training(s,i)
 if r.state!='done':raise HTTPException(409,'仅成功训练可导出')
 return Response(json.dumps(dump(r),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="claim-triage-{i}.json"'})
@router.post('/trainings/{i}/reviews')
def generate(i:int,u=Depends(editor),s=Depends(db)):
 r=ensure_training(s,i)
 if r.state!='done':raise HTTPException(409,'训练完成后才能生成复核任务')
 created=0
 for p in r.result['pending']:
  if p['score']>=r.threshold and not s.query(Review).filter_by(training_id=i,claim_id=p['id']).first():s.add(Review(training_id=i,claim_id=p['id'],score=p['score']));created+=1
 s.commit();audit(s,u,'生成风险复核 '+str(i));return {'created':created}
@router.get('/reviews')
def reviews(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Review).order_by(Review.id.desc()).all()]
@router.put('/reviews/{i}')
def review(i:int,data:ReviewInput,u=Depends(editor),s=Depends(db)):
 r=s.get(Review,i)
 if not r:raise HTTPException(404,'复核任务不存在')
 if r.status=='approved':raise HTTPException(409,'已签核复核不可修改')
 r.decision=data.decision;r.note=data.note;s.commit();audit(s,u,'人工复核 '+str(i));return dump(r)
@router.post('/reviews/{i}/approve')
def approve(i:int,u=Depends(admin),s=Depends(db)):
 r=s.get(Review,i)
 if not r:raise HTTPException(404,'复核任务不存在')
 if r.decision=='pending' or r.status!='draft':raise HTTPException(409,'先填写人工判断，且只签核一次')
 r.status='approved';s.commit();audit(s,u,'签核复核 '+str(i));return dump(r)
@router.get('/audits')
def audits(u=Depends(admin),s=Depends(db)):return [dump(r) for r in s.query(Audit).order_by(Audit.id.desc()).limit(100)]
@router.get('/dp-policy')
def dp_policy(u=Depends(current)):return privacy.policy()
@router.get('/trainings/{i}/privacy')
def ledger(i:int,u=Depends(current),s=Depends(db)):
 ensure_training(s,i);l=privacy.ensure_ledger(s,i)
 return {'training_id':i,'total':l.total,'spent':round(l.spent,6),'remaining':round(l.total-l.spent,6)}
@router.get('/dp-queries')
def dp_queries(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(DpRequest).order_by(DpRequest.id.desc()).limit(200)]
@router.post('/dp-queries')
def dp_query(data:DpQueryInput,u=Depends(editor),s=Depends(db)):
 fp=privacy.fingerprint(data.training_id,data.holiday,data.epsilon)
 existing=s.query(DpRequest).filter_by(request_id=data.request_id).first()
 if existing:
  if existing.fingerprint!=fp:raise HTTPException(409,'同一单号内容不一致，已拒绝；改筛选或预算请使用新单号')
  return dump(existing)
 t=ensure_training(s,data.training_id)
 if t.state!='done':raise HTTPException(409,'仅已完成训练的版本可发起隐私查询')
 privacy.ensure_ledger(s,data.training_id)
 r=DpRequest(request_id=data.request_id,fingerprint=fp,training_id=data.training_id,holiday=data.holiday,epsilon=data.epsilon,actor=u.email,state='accepted',charged=data.epsilon,created=privacy.now())
 s.add(r);charged=privacy.charge(s,data.training_id,data.epsilon)
 if not charged:r.state='failed';r.charged=0.;r.error='版本剩余预算不足本次查询'
 try:s.commit()
 except IntegrityError:
  s.rollback();existing=s.query(DpRequest).filter_by(request_id=data.request_id).first()
  if existing.fingerprint!=fp:raise HTTPException(409,'同一单号内容不一致，已拒绝；改筛选或预算请使用新单号')
  return dump(existing)
 if not charged:raise HTTPException(409,r.error)
 audit(s,u,'隐私查询 '+data.request_id)
 try:result=privacy.aggregate(t.result['snapshot'],data.holiday,data.epsilon)
 except Exception as e:
  privacy.fail(s,r.id,data.training_id,data.epsilon,'统计计算失败：'+str(e)[:180]);raise HTTPException(500,'统计计算失败，未发布，预算已退还')
 row=privacy.publish(s,r.id,result)
 return dump(row or s.get(DpRequest,r.id))
