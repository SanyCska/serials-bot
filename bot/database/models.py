from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from datetime import datetime
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, nullable=False)  # Store as string
    username = Column(String)
    first_name = Column(String)
    last_name = Column(String)
    joined_date = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    series = relationship('UserSeries', back_populates='user')
    
    def __repr__(self):
        return f"<User(id={self.id}, telegram_id={self.telegram_id}, username={self.username})>"

class Series(Base):
    __tablename__ = 'series'
    
    id = Column(Integer, primary_key=True)
    tmdb_id = Column(Integer, unique=True)
    name = Column(String, nullable=False)
    year = Column(Integer)
    total_seasons = Column(Integer)
    last_update = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    users = relationship('UserSeries', back_populates='series')
    
    def __repr__(self):
        return f"<Series(id={self.id}, name={self.name}, tmdb_id={self.tmdb_id})>"

class UserSeries(Base):
    __tablename__ = 'user_series'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    series_id = Column(Integer, ForeignKey('series.id'))
    current_season = Column(Integer, default=1)
    current_episode = Column(Integer, default=0)
    is_watching = Column(Boolean, default=True)
    in_watchlist = Column(Boolean, default=False)
    is_watched = Column(Boolean, default=False)
    watched_date = Column(DateTime)
    last_updated = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship('User', back_populates='series')
    series = relationship('Series', back_populates='users')
    
    def __repr__(self):
        return f"<UserSeries(user_id={self.user_id}, series_id={self.series_id}, season={self.current_season}, episode={self.current_episode})>"

def get_database_url():
    """Construct the database URL from individual POSTGRES_* env variables."""
    db_user = os.getenv('POSTGRES_USER', 'postgres')
    db_password = os.getenv('POSTGRES_PASSWORD', 'postgres')
    db_host = os.getenv('POSTGRES_HOST', 'localhost')
    db_port = os.getenv('POSTGRES_PORT', '5432')
    db_name = os.getenv('POSTGRES_DB', 'serials_bot')
    return f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

def get_session():
    """Get a database session"""
    engine = create_engine(get_database_url())
    Session = sessionmaker(bind=engine)
    return Session()

def init_db():
    """Initialize the database"""
    engine = create_engine(get_database_url())
    Base.metadata.create_all(engine) 