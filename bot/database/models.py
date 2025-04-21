from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
import datetime
import os

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, nullable=False)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    joined_date = Column(DateTime, default=datetime.datetime.utcnow)
    
    series = relationship("UserSeries", back_populates="user", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<User(telegram_id='{self.telegram_id}', username='{self.username}')>"


class Series(Base):
    __tablename__ = 'series'
    
    id = Column(Integer, primary_key=True)
    tmdb_id = Column(Integer, unique=True, nullable=False)
    name = Column(String, nullable=False)
    year = Column(Integer, nullable=True)
    total_seasons = Column(Integer, nullable=True)
    last_update = Column(DateTime, default=datetime.datetime.utcnow)
    
    users = relationship("UserSeries", back_populates="series", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Series(name='{self.name}', year='{self.year}')>"


class UserSeries(Base):
    __tablename__ = 'user_series'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    series_id = Column(Integer, ForeignKey('series.id'), nullable=False)
    current_season = Column(Integer, default=1)
    current_episode = Column(Integer, default=0)
    is_watching = Column(Boolean, default=True)
    in_watchlist = Column(Boolean, default=False)
    is_watched = Column(Boolean, default=False)
    watched_date = Column(DateTime, nullable=True)
    last_updated = Column(DateTime, default=datetime.datetime.utcnow)
    
    user = relationship("User", back_populates="series")
    series = relationship("Series", back_populates="users")
    
    def __repr__(self):
        return f"<UserSeries(user_id='{self.user_id}', series_id='{self.series_id}', current_season='{self.current_season}', current_episode='{self.current_episode}')>"


# Create engine and session
def get_engine(db_path="sqlite:///bot/database/serials.db"):
    return create_engine(db_path)

def get_session():
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()

def init_db():
    engine = get_engine()
    Base.metadata.create_all(engine) 