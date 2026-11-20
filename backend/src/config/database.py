import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
URL=os.environ['DATABASE_URL']
ARGS={'check_same_thread':False,'timeout':30} if URL.startswith('sqlite') else {}
engine=create_engine(URL,pool_pre_ping=True,connect_args=ARGS)
Session=sessionmaker(bind=engine,expire_on_commit=False)
Base=declarative_base()
def db():
 with Session() as s: yield s
