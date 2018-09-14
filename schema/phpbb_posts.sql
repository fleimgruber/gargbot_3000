DROP TABLE IF EXISTS phpbb_posts;

CREATE TABLE phpbb_posts (
    post_id mediumint(8) unsigned NOT NULL auto_increment,
    topic_id mediumint(8) unsigned NOT NULL default '0',
    forum_id mediumint(8) unsigned NOT NULL default '0',
    db_id mediumint(8) unsigned NOT NULL default '0',
    icon_id mediumint(8) unsigned NOT NULL default '0',
    poster_ip varchar(40) collate utf8_bin NOT NULL default '',
    post_time int(11) unsigned NOT NULL default '0',
    post_approved tinyint(1) unsigned NOT NULL default '1',
    post_reported tinyint(1) unsigned NOT NULL default '0',
    enable_bbcode tinyint(1) unsigned NOT NULL default '1',
    enable_smilies tinyint(1) unsigned NOT NULL default '1',
    enable_magic_url tinyint(1) unsigned NOT NULL default '1',
    enable_sig tinyint(1) unsigned NOT NULL default '1',
    post_username varchar(255) collate utf8_bin NOT NULL default '',
    post_subject varchar(255) character set utf8 collate utf8_unicode_ci NOT NULL default '',
    post_text mediumtext character set utf8 collate utf8_unicode_ci NOT NULL,
    post_checksum varchar(32) collate utf8_bin NOT NULL default '',
    post_attachment tinyint(1) unsigned NOT NULL default '0',
    bbcode_bitfield varchar(255) collate utf8_bin NOT NULL default '',
    bbcode_uid varchar(8) collate utf8_bin NOT NULL default '',
    post_postcount tinyint(1) unsigned NOT NULL default '1',
    post_edit_time int(11) unsigned NOT NULL default '0',
    post_edit_reason varchar(255) collate utf8_bin NOT NULL default '',
    post_edit_user mediumint(8) unsigned NOT NULL default '0',
    post_edit_count smallint(4) unsigned NOT NULL default '0',
    post_edit_locked tinyint(1) unsigned NOT NULL default '0',
    PRIMARY KEY  (post_id),
    KEY forum_id (forum_id),
    KEY topic_id (topic_id),
    KEY poster_ip (poster_ip),
    KEY db_id (db_id),
    KEY post_approved (post_approved),
    KEY post_username (post_username),
    KEY tid_post_time (topic_id,post_time)
) ENGINE=MyISAM AUTO_INCREMENT=25421 DEFAULT CHARSET=utf8 COLLATE=utf8_bin;

