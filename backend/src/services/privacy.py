import hashlib,json,math
from datetime import datetime,timezone
from random import SystemRandom
from sqlalchemy.exc import IntegrityError
from src.models.entities import PrivacyLedger,DpRequest
# 预先公开的差分隐私口径：改动即变更对外承诺，须同步 README 与页面
VERSION_BUDGET=3.0      # 每版本总预算 ε，预先固定，各账号共用
AMOUNT_CAP=2000.0       # 单票金额贡献上限（截断，元）
COUNT_CAP=1             # 单票数量贡献上限
ALLOCATION={'count':.5,'amount':.5}  # 预算分配：数量/金额各半
MAX_EPSILON=1.0         # 单请求预算上限
ERROR_CONFIDENCE=.95    # 误差依据：95% 误差界 = 噪声尺度 × ln20
MECHANISM='laplace'
_rng=SystemRandom()
def policy():
 f=math.log(1/(1-ERROR_CONFIDENCE))
 return {'mechanism':'Laplace 噪声','amount_cap':AMOUNT_CAP,'count_cap':COUNT_CAP,'allocation':ALLOCATION,'version_budget':VERSION_BUDGET,'max_epsilon':MAX_EPSILON,'error_confidence':ERROR_CONFIDENCE,'error_basis':f'{ERROR_CONFIDENCE:.0%} 误差界 = 噪声尺度 × ln20 ≈ 尺度 × {f:.3f}；数量尺度 = {COUNT_CAP}/(ε×0.5)，金额尺度 = {AMOUNT_CAP}/(ε×0.5)','empty_set':'空集同样加噪发布，不做特殊处理','raw_sample':'原始样本不出库，仅发布加噪后的数量与金额'}
def fingerprint(training_id,holiday,epsilon):
 return hashlib.sha256(json.dumps({'training_id':training_id,'holiday':holiday,'epsilon':epsilon},sort_keys=True).encode()).hexdigest()
def laplace(scale,rng):
 u=rng.random()
 while u<=0:u=rng.random()
 u-=.5
 return -scale*math.copysign(1,u)*math.log1p(-2*abs(u))
def aggregate(snapshot,holiday,epsilon,rng=None):
 rng=rng or _rng
 rows=[r for r in snapshot if holiday=='all' or bool(r.get('holiday'))==(holiday=='yes')]
 ec,ea=epsilon*ALLOCATION['count'],epsilon*ALLOCATION['amount']
 sc,sa=COUNT_CAP/ec,AMOUNT_CAP/ea
 count=float(len(rows));amount=sum(min(max(float(r.get('amount') or 0),0.),AMOUNT_CAP) for r in rows)
 f=math.log(1/(1-ERROR_CONFIDENCE))
 return {'noisy_count':round(count+laplace(sc,rng),4),'noisy_amount':round(amount+laplace(sa,rng),4),'count_scale':round(sc,6),'amount_scale':round(sa,6),'count_error95':round(sc*f,4),'amount_error95':round(sa*f,4),'epsilon':epsilon,'allocation':ALLOCATION,'amount_cap':AMOUNT_CAP,'mechanism':MECHANISM,'filter':holiday,'note':'原始计数与金额不发布；空集同样加噪；95% 误差界 = 尺度 × ln20'}
def ensure_ledger(s,training_id):
 l=s.get(PrivacyLedger,training_id)
 if l:return l
 s.add(PrivacyLedger(training_id=training_id,total=VERSION_BUDGET,spent=0.))
 try:s.commit()
 except IntegrityError:s.rollback()
 return s.get(PrivacyLedger,training_id)
def charge(s,training_id,epsilon):
 return s.query(PrivacyLedger).filter(PrivacyLedger.training_id==training_id,PrivacyLedger.spent+epsilon<=PrivacyLedger.total).update({'spent':PrivacyLedger.spent+epsilon},synchronize_session=False)
def publish(s,pk,result):
 n=s.query(DpRequest).filter(DpRequest.id==pk,DpRequest.state=='accepted').update({'state':'published','result':result},synchronize_session=False)
 s.commit();s.expire_all();return s.get(DpRequest,pk) if n else None
def fail(s,pk,training_id,charged,error):
 n=s.query(DpRequest).filter(DpRequest.id==pk,DpRequest.state=='accepted').update({'state':'failed','error':error,'refunded':charged},synchronize_session=False)
 if n and charged:s.query(PrivacyLedger).filter(PrivacyLedger.training_id==training_id).update({'spent':PrivacyLedger.spent-charged},synchronize_session=False)
 s.commit();s.expire_all()
def recover(s):
 n=0
 for r in s.query(DpRequest).filter_by(state='accepted').all():
  done=s.query(DpRequest).filter(DpRequest.id==r.id,DpRequest.state=='accepted').update({'state':'failed','error':'服务中断未发布，预算已退还','refunded':r.charged},synchronize_session=False)
  if done and r.charged:s.query(PrivacyLedger).filter(PrivacyLedger.training_id==r.training_id).update({'spent':PrivacyLedger.spent-r.charged},synchronize_session=False)
  n+=done
 s.commit();s.expire_all();return n
def now():return datetime.now(timezone.utc).isoformat()
