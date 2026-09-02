import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Table, Button, Tag, Space, message, Typography, Tabs, Progress, Tooltip } from 'antd';
import { ReloadOutlined, ClockCircleOutlined, EyeOutlined } from '@ant-design/icons';
import request from '@/services/request';

const { Title } = Typography;

/** 格式化耗时：2.5s / 45.8s / 1m 23s / 1h 5m 3s */
function formatDuration(d?: number): string {
  if (!d && d !== 0) return '-';
  if (d < 60) return `${d.toFixed(1)}s`;
  const m = Math.floor(d / 60);
  const s = Math.round(d % 60);
  if (m < 60) return `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return `${h}h ${rm}m ${s}s`;
}

/** 判断是否包含AI分析标记 */
function hasAIAnalysis(r: any): boolean {
  if (!r?.analysis_result) return false;
  try {
    const parsed = typeof r.analysis_result === 'string' ? JSON.parse(r.analysis_result) : r.analysis_result;
    return parsed?.ai_analyzed === true;
  } catch {
    return false;
  }
}

export default function ExecutionListPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [activeTab, setActiveTab] = useState('all');

  const fetchData = useCallback(async (p: number, ps: number, status?: string) => {
    setLoading(true);
    try {
      const res: any = await request.get('/executions/list', {
        params: { page: p, page_size: ps, status: status === 'all' ? undefined : status },
      });
      const d = res.data || res;
      setData(d?.items || []);
      setTotal(d?.total || 0);
    } catch {
      message.error('加载执行列表失败');
      setData([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(page, pageSize, activeTab); }, [page, pageSize, activeTab, fetchData]);

  const statusMap: Record<string, { color: string; text: string }> = {
    success: { color: 'green', text: '成功' },
    failed: { color: 'red', text: '失败' },
    running: { color: 'blue', text: '执行中' },
    waiting: { color: 'orange', text: '等待中' },
    cancelled: { color: 'default', text: '已取消' },
    pending: { color: 'orange', text: '排队中' },
  };

  return (
    <div>
      <Card
        title={<Title level={4} style={{ margin: 0 }}>测试执行</Title>}
        extra={
          <Space>
            <Button icon={<ClockCircleOutlined />} onClick={() => navigate('/execution/schedule')}>定时任务</Button>
            <Button icon={<ReloadOutlined />} onClick={() => fetchData(page, pageSize, activeTab)}>刷新</Button>
          </Space>
        }
      >
        <Tabs
          activeKey={activeTab}
          onChange={(k) => { setActiveTab(k); setPage(1); }}
          items={[
            { key: 'all', label: '全部' },
            { key: 'running', label: '执行中' },
            { key: 'success', label: '成功' },
            { key: 'failed', label: '失败' },
          ]}
        />

        <Table
          dataSource={data}
          rowKey="id"
          loading={loading}
          size="middle"
          scroll={{ x: 1300 }}
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
            { title: '类型', dataIndex: 'execution_type', width: 100,
              render: (t: string) => {
                const map: Record<string, { color: string; text: string }> = {
                  web: { color: 'blue', text: 'Web' },
                  api: { color: 'cyan', text: 'API' },
                  android: { color: 'geekblue', text: 'Android' },
                  suite: { color: 'purple', text: '套件' },
                  batch: { color: 'magenta', text: '批量' },
                };
                const info = map[t] || { color: 'default', text: t };
                return <Tag color={info.color}>{info.text}</Tag>;
              },
            },
            { title: '状态', dataIndex: 'status', width: 100,
              render: (s: string) => {
                const info = statusMap[s] || { color: 'default', text: s };
                return <Tag color={info.color}>{info.text}</Tag>;
              },
            },
            { title: '通过率', width: 150,
              render: (_, r: any) => {
                const total = (r.success_count || 0) + (r.failed_count || 0);
                const rate = total > 0 ? Math.round((r.success_count || 0) / total * 100) : 0;
                return (
                  <div style={{ minWidth: 100 }}>
                    <Progress percent={rate} size="small" strokeColor={rate >= 80 ? '#52c41a' : rate >= 50 ? '#faad14' : '#ff4d4f'} />
                  </div>
                );
              },
            },
            { title: '通过/失败', width: 130,
              render: (_, r: any) => (
                <Space size={4}>
                  <Tag color="green">{r.success_count || 0} 通过</Tag>
                  <Tag color="red">{r.failed_count || 0} 失败</Tag>
                </Space>
              ),
            },
            { title: 'AI分析', width: 90,
              render: (_: any, r: any) => hasAIAnalysis(r) ? <Tag color="geekblue">AI分析</Tag> : <Tag>无</Tag>,
            },
            { title: '耗时', dataIndex: 'duration', width: 110,
              render: (d: number) => formatDuration(d),
            },
            { title: '任务ID', dataIndex: 'task_id', width: 80, render: (id: number) => id || '-' },
            { title: '执行时间', dataIndex: 'start_time', width: 180, render: (t: string) => t || '-' },
            { title: '操作', width: 200, fixed: 'right' as const,
              render: (_: any, r: any) => (
                <Space>
                  <Tooltip title="执行详情">
                    <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => navigate(`/execution/detail/${r.id}`)}>执行详情</Button>
                  </Tooltip>
                  <Button type="link" size="small" onClick={() => window.open(`/api/executions/${r.id}/report?format=html`, '_blank')}>报告</Button>
                </Space>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}
