-- Kunlun Alpha — PostgreSQL 初始化脚本
-- 首次启动时由 docker-entrypoint-initdb.d 自动执行

-- 启用 UUID 扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 设置默认 schema 搜索路径
ALTER DATABASE kunlun SET search_path TO kunlun, public;

-- 创建应用 schema（Table-per-schema 多租户预备）
CREATE SCHEMA IF NOT EXISTS kunlun;

-- 设置 schema 权限
GRANT ALL ON SCHEMA kunlun TO kunlun;

-- 日志：确认初始化完成
DO $$
BEGIN
  RAISE NOTICE 'PostgreSQL init complete: database=kunlun, schema=kunlun';
END $$;
