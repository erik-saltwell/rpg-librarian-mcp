-- Drops every table/index created by create_schema.sql, in dependency order
-- (children before parents). Indexes are dropped implicitly with their table
-- and are not listed separately.

DROP TABLE IF EXISTS entry_text;

DROP TABLE IF EXISTS pdf_metadata;
DROP TABLE IF EXISTS image_metadata;
DROP TABLE IF EXISTS svg_metadata;
DROP TABLE IF EXISTS audio_metadata;
DROP TABLE IF EXISTS mesh_metadata;
DROP TABLE IF EXISTS video_metadata;

DROP TABLE IF EXISTS entries;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS schema_meta;
