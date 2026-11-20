"""差分隐私共享验证：预算竞争 / 空集 / 发布后响应丢失再重试 / 并发同号 / 中断恢复 / 守卫。
运行：/tmp/dpenv/bin/python -m pytest dp_test.py -v   （仓库根外 test-artifacts，不污染源码）
"""
import os,sys,math,time,random,threading,pathlib,tempfile
ROOT=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
TMP=tempfile.mkdtemp(prefix='dptest_')
os.environ['DATABASE_URL']='sqlite:///'+TMP+'/test.db'
os.environ['REDIS_URL']='redis://127.0.0.1:6390/0'   # 本套验证不触达队列
os.environ['JWT_SECRET']='dp-test-secret'
os.environ.pop('SEED_DEMO',None)
import httpx,uvicorn,pytest
from fastapi.testclient import TestClient
from src.main import app
from src.config.database import Session,Base,engine
from src.models.entities import User,Training,DpRequest,PrivacyLedger
from src.utils.security import hash_password
from src.services import privacy

BASE='http://127.0.0.1:19321'
def rows(n,holiday=False,amount=100.0):
 return [{'id':i+1,'code':f'T-{i+1:03}','amount':amount*(1+i%5),'distance':10.0+i,'holiday':holiday,'label':i%2,'note':''} for i in range(n)]
def make_training(state='done',snapshot=None):
 with Session() as s:
  t=Training(name='dp-验证',threshold=.5,state=state,result={'snapshot':snapshot if snapshot is not None else rows(60)})
  s.add(t);s.commit();return t.id
def make_user(email,role):
 with Session() as s:
  if not s.query(User).filter_by(email=email).first():s.add(User(email=email,role=role,password=hash_password('Demo123!')));s.commit()
def token(c,email):
 r=c.post('/auth/login',json={'email':email,'password':'Demo123!'});assert r.status_code==200,r.text
 return {'Authorization':'Bearer '+r.json()['token']}
def ledger(tid):
 with Session() as s:
  l=s.get(PrivacyLedger,tid);return (l.total,l.spent) if l else (None,None)
def reqs(rid):
 with Session() as s:return s.query(DpRequest).filter_by(request_id=rid).all()

@pytest.fixture(scope='module',autouse=True)
def boot():
 Base.metadata.create_all(engine)
 for e,r in [('admin@demo.local','admin'),('analyst@demo.local','analyst'),('viewer@demo.local','viewer')]:make_user(e,r)
 yield

def test_empty_set():
 """空集也同样加噪：快照全为非节假日，筛选“仅节假日”命中 0 笔，仍发布加噪结果且不泄露原始计数。"""
 tid=make_training(snapshot=rows(50,holiday=False))
 with TestClient(app) as c:
  h=token(c,'analyst@demo.local')
  r=c.post('/dp-queries',json={'request_id':'DP-EMPTY-1','training_id':tid,'holiday':'yes','epsilon':0.8},headers=h)
  assert r.status_code==200,r.text
  q=r.json();assert q['state']=='published' and q['charged']==0.8
  res=q['result']
  assert set(res)<={'noisy_count','noisy_amount','count_scale','amount_scale','count_error95','amount_error95','epsilon','allocation','amount_cap','mechanism','filter','note'}
  assert isinstance(res['noisy_count'],float) and isinstance(res['noisy_amount'],float)
  f=math.log(20)
  assert res['count_scale']==pytest.approx(1/0.4) and res['count_error95']==pytest.approx(2.5*f,abs=1e-4)
  assert res['amount_scale']==pytest.approx(2000/0.4) and res['amount_error95']==pytest.approx(5000*f,abs=1e-2)
 # 单元层：固定种子下空集噪声确定非零且可复现（证明空集走同一加噪路径）
 a=privacy.aggregate([],'all',0.5,rng=random.Random(3));b=privacy.aggregate([],'all',0.5,rng=random.Random(3))
 assert a==b and (a['noisy_count']!=0 or a['noisy_amount']!=0)

def test_retry_after_response_loss():
 """发布后响应丢失再重试：返回原噪声、不重复扣费；同号异内容拒绝；改筛选/预算须新单号。"""
 tid=make_training()
 with TestClient(app) as c:
  h=token(c,'analyst@demo.local')
  body={'request_id':'DP-RETRY-1','training_id':tid,'holiday':'all','epsilon':0.5}
  r1=c.post('/dp-queries',json=body,headers=h);assert r1.status_code==200,r1.text
  n1=(r1.json()['result']['noisy_count'],r1.json()['result']['noisy_amount'])
  spent1=ledger(tid)[1];assert spent1==pytest.approx(0.5)
  r2=c.post('/dp-queries',json=body,headers=h)          # 模拟响应丢失后重试
  assert r2.status_code==200
  n2=(r2.json()['result']['noisy_count'],r2.json()['result']['noisy_amount'])
  assert n1==n2,'重试必须返回原噪声'
  assert ledger(tid)[1]==pytest.approx(spent1),'重试不得重复扣费'
  assert len(reqs('DP-RETRY-1'))==1
  for diff in ({'epsilon':0.6},{'holiday':'yes'}):       # 同号异内容
   bad=dict(body,**diff);r=c.post('/dp-queries',json=bad,headers=h)
   assert r.status_code==409 and '同一单号' in r.json()['detail']
  assert ledger(tid)[1]==pytest.approx(spent1)
  r3=c.post('/dp-queries',json={'request_id':'DP-RETRY-2','training_id':tid,'holiday':'yes','epsilon':0.5},headers=h)
  assert r3.status_code==200,'改筛选用新单号算新请求'
  assert ledger(tid)[1]==pytest.approx(1.0)

def test_concurrent_same_request_id():
 """并发同号同内容：全部返回同一条，预算只扣一次。"""
 tid=make_training()
 body={'request_id':'DP-RACE-1','training_id':tid,'holiday':'no','epsilon':0.5}
 with TestClient(app) as c:
  h=token(c,'analyst@demo.local')
  with httpx.Client(base_url=str(c.base_url),headers=h) as hc:  # 顺序预热确认可用
   pass
  out=[]
  def hit():
   with TestClient(app) as cc:    # 每线程独立客户端，模拟并发重试风暴
    out.append(cc.post('/dp-queries',json=body,headers=token(cc,'analyst@demo.local')))
  ts=[threading.Thread(target=hit) for _ in range(6)]
  [t.start() for t in ts];[t.join() for t in ts]
  assert all(r.status_code==200 for r in out),[r.text for r in out]
  noises={(r.json()['result']['noisy_count'],r.json()['result']['noisy_amount']) for r in out}
  assert len(noises)==1,'并发同号必须返回同一噪声'
  assert len(reqs('DP-RACE-1'))==1
  assert ledger(tid)[1]==pytest.approx(0.5),'并发同号只扣一次预算'

def test_budget_contention():
 """预算竞争：真 HTTP 服务 8 并发 × ε=1.0，总预算 3.0，恰好 3 单发布、其余预算不足，绝不超支。"""
 tid=make_training()
 cfg=uvicorn.Config(app,host='127.0.0.1',port=19321,log_level='error')
 srv=uvicorn.Server(cfg);th=threading.Thread(target=srv.run,daemon=True);th.start()
 try:
  for _ in range(100):
   try:httpx.get(BASE+'/docs',timeout=1);break
   except Exception:time.sleep(.1)
  else:raise RuntimeError('server not up')
  h=token(httpx.Client(base_url=BASE),'analyst@demo.local')
  out=[]
  def hit(k):
   r=httpx.post(BASE+'/dp-queries',json={'request_id':f'DP-WAR-{k}','training_id':tid,'holiday':'all','epsilon':1.0},headers=h,timeout=30)
   out.append((r.status_code,r.json()))
  ts=[threading.Thread(target=hit,args=(k,)) for k in range(8)]
  [t.start() for t in ts];[t.join() for t in ts]
 finally:
  srv.should_exit=True;th.join(timeout=10)
  ok=[q for s,q in out if s==200];denied=[q for s,q in out if s==409]
  assert len(ok)==3 and len(denied)==5,f'8 单竞争 3.0 ε：{[(s,q.get("state")) for s,q in out]}'
  total,spent=ledger(tid)
  assert total==3.0 and spent==pytest.approx(3.0),'并发扣减不得超支'
  assert all(q['state']=='published' and q['charged']==1.0 and q['result'] for q in ok),'结果可见即预算已扣'
  assert all('预算' in q['detail'] for q in denied)
  with Session() as s:
   fails=s.query(DpRequest).filter(DpRequest.request_id.like('DP-WAR-%'),DpRequest.state=='failed').all()
   assert len(fails)==5 and all(f.charged==0 and f.refunded==0 for f in fails),'预算不足单从未扣费，无需退还'

def test_recovery_keeps_published():
 """中断恢复：受理中未发布的退还；已发布结果不再退款。"""
 tid=make_training()
 make_training_id=tid
 with Session() as s:
  privacy.ensure_ledger(s,tid)
  assert privacy.charge(s,tid,0.7)==1
  s.add(DpRequest(request_id='DP-CRASH-1',fingerprint='x',training_id=tid,holiday='all',epsilon=0.7,actor='analyst@demo.local',state='accepted',charged=0.7,created=privacy.now()))
  assert privacy.charge(s,tid,0.4)==1
  s.add(DpRequest(request_id='DP-CRASH-2',fingerprint='y',training_id=tid,holiday='all',epsilon=0.4,actor='analyst@demo.local',state='published',charged=0.4,result={'noisy_count':1.0,'noisy_amount':2.0},created=privacy.now()))
  s.commit()
 assert ledger(tid)[1]==pytest.approx(1.1)
 with Session() as s:n=privacy.recover(s)
 assert n==1
 with Session() as s:
  a=s.query(DpRequest).filter_by(request_id='DP-CRASH-1').one()
  b=s.query(DpRequest).filter_by(request_id='DP-CRASH-2').one()
  assert a.state=='failed' and a.refunded==0.7 and '中断' in a.error
  assert b.state=='published' and b.refunded==0 and b.result['noisy_count']==1.0,'已发布结果不退款'
 assert ledger(tid)[1]==pytest.approx(0.4),'只退还未曝光部分'

def test_guards():
 tid=make_training();queued=make_training(state='queued')
 with TestClient(app) as c:
  hv=token(c,'viewer@demo.local');ha=token(c,'analyst@demo.local')
  assert c.post('/dp-queries',json={'request_id':'DP-G-1','training_id':tid,'epsilon':0.5},headers=hv).status_code==403
  assert c.post('/dp-queries',json={'request_id':'DP-G-2','training_id':queued,'epsilon':0.5},headers=ha).status_code==409
  assert c.post('/dp-queries',json={'request_id':'DP-G-3','training_id':tid,'epsilon':2.0},headers=ha).status_code==422
  assert c.post('/dp-queries',json={'request_id':'DP-G-4','training_id':tid,'holiday':'bad','epsilon':0.5},headers=ha).status_code==422
  assert c.post('/dp-queries',json={'request_id':'DP-G-5','training_id':99999,'epsilon':0.5},headers=ha).status_code==404
  r=c.get('/trainings/'+str(tid)+'/privacy',headers=hv);assert r.status_code==200 and r.json()['remaining']==3.0
  assert c.get('/dp-policy',headers=hv).json()['amount_cap']==2000.0
