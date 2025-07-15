-- Create the database
CREATE DATABASE legal_chatbot;

-- Use the database
USE legal_chatbot;

-- Create chat_session table
CREATE TABLE chat_session (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(255),
    password VARCHAR(255),
    session_id INT,
    start_time DATETIME,
    questions_answers JSON
);

-- Replace with your actual MySQL username and password
CREATE USER 'your_mysql_user'@'localhost' IDENTIFIED BY 'your_mysql_password';

-- Grant permissions to the user on the legal_chatbot database
GRANT ALL PRIVILEGES ON legal_chatbot.* TO 'your_mysql_user'@'localhost';

-- Apply changes
FLUSH PRIVILEGES;

-- Optional: if you had an older table without the password column
-- ALTER TABLE chat_session ADD COLUMN password VARCHAR(255);

-- View contents (for testing/debugging)
SELECT * FROM chat_session;
