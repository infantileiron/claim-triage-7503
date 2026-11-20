from sqlalchemy import Column,Integer,String,Float,JSON,Text,ForeignKey,Boolean,UniqueConstraint
from src.config.database import Base
class User(Base):
 __tablename__='users'
 id=Column(Integer,primary_key=True);email=Column(String(100),unique=True);password=Column(String(200));role=Column(String(20))
class Claim(Base):
 __tablename__='claims'
 id=Column(Integer,primary_key=True);code=Column(String(60),unique=True,nullable=False);amount=Column(Float);distance=Column(Float);holiday=Column(Boolean);label=Column(Integer,nullable=True);note=Column(Text,default='')
class Training(Base):
 __tablename__='trainings'
 id=Column(Integer,primary_key=True);name=Column(String(100));threshold=Column(Float);state=Column(String(20),default='queued');result=Column(JSON);error=Column(Text,default='')
class Review(Base):
 __tablename__='reviews'
 __table_args__=(UniqueConstraint('training_id','claim_id',name='uq_review_source'),)
 id=Column(Integer,primary_key=True);training_id=Column(Integer,ForeignKey('trainings.id'));claim_id=Column(Integer,ForeignKey('claims.id'));score=Column(Float);decision=Column(String(30),default='pending');note=Column(Text,default='');status=Column(String(20),default='draft')
class PrivacyLedger(Base):
 __tablename__='privacy_ledgers'
 training_id=Column(Integer,ForeignKey('trainings.id'),primary_key=True);total=Column(Float,nullable=False);spent=Column(Float,default=0)
class DpRequest(Base):
 __tablename__='dp_requests'
 id=Column(Integer,primary_key=True);request_id=Column(String(64),unique=True,nullable=False);fingerprint=Column(String(64));training_id=Column(Integer,ForeignKey('trainings.id'));holiday=Column(String(10));epsilon=Column(Float);actor=Column(String(100));state=Column(String(20),default='accepted');charged=Column(Float,default=0);refunded=Column(Float,default=0);result=Column(JSON,nullable=True);error=Column(Text,default='');created=Column(String(40))
class Audit(Base):
 __tablename__='audits'
 id=Column(Integer,primary_key=True);actor=Column(String(100));action=Column(String(200));created=Column(String(40))
