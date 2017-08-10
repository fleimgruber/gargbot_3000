DROP TABLE IF EXISTS dbx_pictures;

CREATE TABLE dbx_pictures (
path CHAR(100),
topic CHAR(30));

ALTER TABLE dbx_pictures
ADD taken datetime,
ADD pic_id INT PRIMARY KEY AUTO_INCREMENT;

CREATE TABLE faces (
garg_id INT PRIMARY KEY,
name char(30)
);

CREATE TABLE dbx_pictures_faces (
garg_id INT,
pic_id INT
);