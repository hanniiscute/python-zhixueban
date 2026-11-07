"""数据库迁移 — MySQL 建表语句"""

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(64) PRIMARY KEY,
    username VARCHAR(64) NOT NULL UNIQUE,
    password_hash VARCHAR(255) DEFAULT '',
    display_name VARCHAR(64) DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP NULL DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    course VARCHAR(64) DEFAULT 'Python程序设计',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_sessions_user (user_id),
    CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

CREATE_PROFILES = """
CREATE TABLE IF NOT EXISTS profiles (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(64) DEFAULT NULL,
    dimension VARCHAR(64) NOT NULL,
    field VARCHAR(64) NOT NULL,
    value TEXT NOT NULL,
    confidence DOUBLE DEFAULT 0.5,
    evidence TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_profiles_user (user_id),
    INDEX idx_profiles_dim (dimension, field),
    UNIQUE KEY uq_profile (user_id, dimension, field),
    CONSTRAINT fk_profiles_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

CREATE_RESOURCES = """
CREATE TABLE IF NOT EXISTS resources (
    id VARCHAR(64) PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    type VARCHAR(32) NOT NULL,
    title VARCHAR(255) NOT NULL,
    topic VARCHAR(128) DEFAULT '',
    content MEDIUMTEXT,
    metadata_json TEXT,
    user_rating DOUBLE DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_resources_session (session_id),
    CONSTRAINT fk_resources_session FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

CREATE_LEARNING_PATHS = """
CREATE TABLE IF NOT EXISTS learning_paths (
    id VARCHAR(64) PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL UNIQUE,
    path_json MEDIUMTEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_paths_session FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

CREATE_EVALUATIONS = """
CREATE TABLE IF NOT EXISTS evaluations (
    id VARCHAR(64) PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    eval_type VARCHAR(32) NOT NULL,
    data_json MEDIUMTEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_eval_session (session_id),
    CONSTRAINT fk_eval_session FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

CREATE_LEARNING_RECORDS = """
CREATE TABLE IF NOT EXISTS learning_records (
    id INT PRIMARY KEY AUTO_INCREMENT,
    session_id VARCHAR(64) NOT NULL,
    topic VARCHAR(128) NOT NULL,
    resource_id VARCHAR(64) DEFAULT NULL,
    time_spent_minutes INT DEFAULT 0,
    self_evaluation TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_records_session (session_id),
    CONSTRAINT fk_records_session FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

CREATE_CHAT_MESSAGES = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id INT PRIMARY KEY AUTO_INCREMENT,
    session_id VARCHAR(64) NOT NULL,
    role VARCHAR(16) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_chat_session (session_id, created_at),
    CONSTRAINT fk_chat_msg_session FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

CREATE_WRONG_QUESTIONS = """
CREATE TABLE IF NOT EXISTS wrong_questions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    session_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    topic VARCHAR(128) DEFAULT '',
    stem TEXT NOT NULL,
    options_json TEXT,
    answer VARCHAR(255) DEFAULT '',
    user_answer VARCHAR(255) DEFAULT '',
    explanation TEXT,
    resolved TINYINT DEFAULT 0,
    wrong_count INT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_wrong_session (session_id, resolved),
    INDEX idx_wrong_user (user_id, resolved),
    CONSTRAINT fk_wrong_session FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

ALL_TABLES = [
    ("users", CREATE_USERS),
    ("sessions", CREATE_SESSIONS),
    ("profiles", CREATE_PROFILES),
    ("resources", CREATE_RESOURCES),
    ("learning_paths", CREATE_LEARNING_PATHS),
    ("evaluations", CREATE_EVALUATIONS),
    ("learning_records", CREATE_LEARNING_RECORDS),
    ("chat_messages", CREATE_CHAT_MESSAGES),
    ("wrong_questions", CREATE_WRONG_QUESTIONS),
]
