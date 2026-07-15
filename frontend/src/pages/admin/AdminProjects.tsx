import { useState, useEffect, useCallback } from 'react';
import { Card, Table, Button, Tag, message } from 'antd';
import { ProjectOutlined, ReloadOutlined } from '@ant-design/icons';
import { PageHeader } from '../../components/UI';
import request from '../../services/request';

interface ProjectItem {
  id: number;
  name: string;
  task_count?: number;
  tasks_count?: number;
}

export default function AdminProjects() {
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchProjects = useCallback(async () => {
    setLoading(true);
    try {
      const res: any = await request.get('/admin/projects');
      const data = res?.data;
      // 兼容 data 为数组或 { items: [] } 两种结构
      setProjects(Array.isArray(data) ? data : data?.items || []);
    } catch {
      message.error('获取项目列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  const columns = [
    {
      title: '项目名',
      dataIndex: 'name',
      key: 'name',
      render: (t: string) => <Tag color="blue">{t || '-'}</Tag>,
    },
    {
      title: '任务数',
      key: 'task_count',
      render: (_: unknown, r: ProjectItem) => r.task_count ?? r.tasks_count ?? 0,
    },
  ];

  return (
    <div>
      <PageHeader title="项目管理" subtitle="管理测试项目和项目配置" icon={<ProjectOutlined />} />
      <Card extra={<Button icon={<ReloadOutlined />} onClick={fetchProjects}>刷新</Button>}>
        <Table columns={columns} dataSource={projects} rowKey="id" loading={loading} pagination={false} />
      </Card>
    </div>
  );
}
