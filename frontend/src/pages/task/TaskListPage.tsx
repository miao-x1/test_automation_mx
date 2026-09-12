import { useState, useEffect, useCallback } from 'react';
import { Card, Drawer, Descriptions, Table, Button, Input, Tag, Space, message, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import request from '@/services/request';
import { getCurrentProjectId, getCurrentProjectName, PROJECT_CHANGED } from '@/pages/product/projectStore';

const { Title } = Typography;

export default function TaskListPage() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [keyword, setKeyword] = useState('');
  const [projectName, setProjectName] = useState(getCurrentProjectName());
  const [detail, setDetail] = useState<any | null>(null);

  const fetchData = useCallback(async (p: number, ps: number, kw: string) => {
    setLoading(true);
    try {
      const res: any = await request.get('/requirement/list', {
        params: { page: p, page_size: ps, keyword: kw.trim() || undefined, project_id: getCurrentProjectId() || undefined },
      });
      const d = res.data || res;
      const items = Array.isArray(d) ? d : (d?.items || []);
      setData(items);
      setTotal(typeof d?.total === 'number' ? d.total : items.length);
    } catch {
      message.error('加载任务列表失败');
      setData([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(page, pageSize, keyword); }, [page, pageSize, fetchData]);
  useEffect(() => {
    const reload = () => {
      setProjectName(getCurrentProjectName());
      fetchData(1, pageSize, keyword);
    };
    window.addEventListener(PROJECT_CHANGED, reload);
    return () => window.removeEventListener(PROJECT_CHANGED, reload);
  }, [fetchData, pageSize, keyword]);

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
        title={<Title level={4} style={{ margin: 0 }}>测试任务{projectName ? ` · ${projectName}` : ''}</Title>}
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
                <Button type="link" onClick={() => setDetail(r)}>{name || r.requirement || `任务 #${r.id}`}</Button>
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
                <Button type="link" size="small" onClick={() => setDetail(r)}>查看详情</Button>
              ),
            },
          ]}
        />
      </Card>
      <Drawer
        title={detail ? (detail.task_name || detail.requirement || `任务 #${detail.id}`) : '任务详情'}
        open={!!detail}
        onClose={() => setDetail(null)}
        width={520}
      >
        {detail ? (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="ID">{detail.id}</Descriptions.Item>
            <Descriptions.Item label="名称">{detail.task_name || detail.requirement || '-'}</Descriptions.Item>
            <Descriptions.Item label="状态">{detail.status || '-'}</Descriptions.Item>
            <Descriptions.Item label="类型">{detail.task_type || '-'}</Descriptions.Item>
            <Descriptions.Item label="创建时间">{detail.created_at || '-'}</Descriptions.Item>
            {detail.requirement ? <Descriptions.Item label="需求">{detail.requirement}</Descriptions.Item> : null}
          </Descriptions>
        ) : null}
      </Drawer>
    </div>
  );
}
