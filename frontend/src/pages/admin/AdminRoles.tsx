import { useState, useEffect, useCallback } from 'react';
import { Card, Table, Button, Tag, message } from 'antd';
import { SafetyOutlined, ReloadOutlined } from '@ant-design/icons';
import { PageHeader } from '../../components/UI';
import request from '../../services/request';

interface RoleItem {
  id: number;
  name: string;
  description: string;
  permissions_count?: number;
  permission_count?: number;
  users_count?: number;
  user_count?: number;
}

export default function AdminRoles() {
  const [roles, setRoles] = useState<RoleItem[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchRoles = useCallback(async () => {
    setLoading(true);
    try {
      const res: any = await request.get('/admin/roles');
      const data = res?.data;
      // 兼容 data 为数组或 { items: [] } 两种结构
      setRoles(Array.isArray(data) ? data : data?.items || []);
    } catch {
      message.error('获取角色列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRoles();
  }, [fetchRoles]);

  const columns = [
    {
      title: '角色名',
      dataIndex: 'name',
      key: 'name',
      render: (t: string) => <Tag color="blue">{t || '-'}</Tag>,
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (t: string) => t || '-',
    },
    {
      title: '权限数',
      key: 'permissions_count',
      render: (_: unknown, r: RoleItem) => r.permissions_count ?? r.permission_count ?? 0,
    },
    {
      title: '用户数',
      key: 'users_count',
      render: (_: unknown, r: RoleItem) => r.users_count ?? r.user_count ?? 0,
    },
  ];

  return (
    <div>
      <PageHeader title="角色权限" subtitle="管理角色和权限策略" icon={<SafetyOutlined />} />
      <Card extra={<Button icon={<ReloadOutlined />} onClick={fetchRoles}>刷新</Button>}>
        <Table columns={columns} dataSource={roles} rowKey="id" loading={loading} pagination={false} />
      </Card>
    </div>
  );
}
