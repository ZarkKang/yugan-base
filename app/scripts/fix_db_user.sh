#!/bin/bash
echo "=== 1. 创建 warehouse_admin 用户(如不存在) ==="
sudo -u postgres psql -c "DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='warehouse_admin') THEN CREATE ROLE warehouse_admin WITH LOGIN PASSWORD 'CHANGE_ME_DB_PASSWORD'; ELSE ALTER ROLE warehouse_admin WITH LOGIN PASSWORD 'CHANGE_ME_DB_PASSWORD'; END IF; END \$\$;" 2>&1
echo
echo "=== 2. 授予 warehouse_inspection 数据库权限 ==="
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE warehouse_inspection TO warehouse_admin;" 2>&1
echo
echo "=== 3. 授予 public schema 下所有表/序列权限 ==="
sudo -u postgres psql -d warehouse_inspection -c "GRANT ALL ON SCHEMA public TO warehouse_admin; GRANT ALL ON ALL TABLES IN SCHEMA public TO warehouse_admin; GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO warehouse_admin;" 2>&1
echo
echo "=== 4. 授予未来新建表的默认权限 ==="
sudo -u postgres psql -d warehouse_inspection -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO warehouse_admin; ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO warehouse_admin;" 2>&1
echo
echo "=== 5. 验证: 用 warehouse_admin 连接 ==="
PGPASSWORD=CHANGE_ME_DB_PASSWORD psql -h 127.0.0.1 -U warehouse_admin -d warehouse_inspection -c "SELECT COUNT(*) AS user_count FROM users;" 2>&1
echo
echo "=== 6. 验证 users 表查询 ==="
PGPASSWORD=CHANGE_ME_DB_PASSWORD psql -h 127.0.0.1 -U warehouse_admin -d warehouse_inspection -c "SELECT id, username, role, is_active FROM users LIMIT 5;" 2>&1

