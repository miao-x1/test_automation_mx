import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Table, Button, Input, Tag, Space, message, Typography } from 'antd';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import request from '@/services/request';

const { Title } = Typography;

export default function TaskListPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [keyword, setKeyword] = useState('');

  const fetchData = useCallback(async (p: number, ps: number, kw: string) => {
    setLoading(true);
    try {
      const res: any = await request.get('/tasks/', {
        params: { page: p, page_size: ps, keyword: kw.trim() || undefined },
      });
      const d = res.data || res;
      setData(d?.items || []);
      setTotal(d?.total || 0);
    } catch {
      message.error('加载任务列表失败');
      setData([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(page, pageSize, keyword); }, [page, pageSize, fetchData]);

  const statusMap: Record<string, { color: string; text: string }> = {
    pending: { color: 'orange', text: '等待中' },
    running: { color: 'blue', text: '执行中' },
    success: { color: 'green', text: '成功' },
    failed: { color: 'red', text: '失败' },
    completed: { color: 'green', text: '已完成' },
    analyzing: { color: 'blue', text: '分析中' },
  };

  return (
    <div>
      <Card
        title={<Title level={4} style={{ margin: 0 }}>测试任务</Title>}
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/task/create')}>
            创建测试
          </Button>
        }
      >
        <Space style={{ marginBottom: 16 }}>
          <Input.Search
            placeholder="搜索任务名称"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onSearch={() => { setPage(1); fetchData(1, pageSize, keyword); }}
            style={{ width: 300 }}
            allowClear
          />
          <Button icon={<ReloadOutlined />} onClick={() => fetchData(page, pageSize, keyword)}>刷新</Button>
        </Space>

        <Table
          dataSource={data}
          rowKey="id"
          loading={loading}
          size="middle"
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps); },
          }}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 70 },
            { title: '任务名称', dataIndex: 'task_name', ellipsis: true,
              render: (name: string, r: any) => (
                <Button type="link" onClick={() => navigate(`/task/${r.id}`)}>{name || `任务 #${r.id}`}</Button>
              ),
            },
            { title: '状态', dataIndex: 'status', width: 100,
              render: (s: string) => {
                const info = statusMap[s] || { color: 'default', text: s };
                return <Tag color={info.color}>{info.text}</Tag>;
              },
            },
            { title: '类型', dataIndex: 'task_type', width: 100,
              render: (t: string) => {
                const map: Record<string, string> = { web: 'Web', api: 'API', android: 'Android', performance: '性能' };
                return map[t] || t || '-';
              },
            },
            { title: '创建时间', dataIndex: 'created_at', width: 180,
              render: (t: string) => t || '-',
            },
            { title: '操作', width: 120, fixed: 'right' as const,
              render: (_: any, r: any) => (
                <Button type="link" size="small" onClick={() => navigate(`/task/${r.id}`)}>查看详情</Button>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}
