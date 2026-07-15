import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Table, Button, Tag, Space, message, Typography, Tooltip, Row, Col, Statistic, Progress } from 'antd';
import { EyeOutlined, DownloadOutlined, ReloadOutlined, FileTextOutlined, CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons';
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

export default function ReportListPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const fetchData = useCallback(async (p: number, ps: number) => {
    setLoading(true);
    try {
      const res: any = await request.get('/executions/list', {
        params: { page: p, page_size: ps },
      });
      const d = res.data || res;
      // 只显示已完成的执行
      const completed = (d?.items || []).filter((item: any) =>
        item.status === 'success' || item.status === 'failed' || item.status === 'cancelled'
      );
      setData(completed);
      setTotal(completed.length);
    } catch {
      message.error('加载报告列表失败');
      setData([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(page, pageSize); }, [page, pageSize, fetchData]);

  // 统计数据
  const passedCount = data.filter((d) => d.status === 'success').length;
  const failedCount = data.filter((d) => d.status === 'failed').length;
  const passRate = data.length > 0 ? Math.round((passedCount / data.length) * 1000) / 10 : 0;

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic title="执行总数" value={data.length} prefix={<FileTextOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="通过" value={passedCount} valueStyle={{ color: '#52c41a' }} prefix={<CheckCircleOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="失败" value={failedCount} valueStyle={{ color: '#ff4d4f' }} prefix={<CloseCircleOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="通过率" value={passRate} suffix="%" precision={1} />
            <Progress percent={passRate} showInfo={false} strokeColor="#52c41a" style={{ marginTop: 8 }} />
          </Card>
        </Col>
      </Row>

      <Card
        title={<Title level={4} style={{ margin: 0 }}><FileTextOutlined /> 测试报告</Title>}
        extra={<Button icon={<ReloadOutlined />} onClick={() => fetchData(page, pageSize)}>刷新</Button>}
      >
        <Table
          dataSource={data}
          rowKey="id"
          loading={loading}
          size="middle"
          scroll={{ x: 1200 }}
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
            { title: '任务名称', dataIndex: 'task_name', width: 160, ellipsis: true,
              render: (name: string, r: any) => name || r.requirement || r.task_id || '-',
            },
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
            { title: 'AI分析', width: 90,
              render: (_: any, r: any) => hasAIAnalysis(r) ? <Tag color="geekblue">AI分析</Tag> : <Tag>无</Tag>,
            },
            { title: '结果', dataIndex: 'status', width: 100,
              render: (s: string) => {
                const map: Record<string, { color: string; text: string }> = {
                  success: { color: 'green', text: '通过' },
                  failed: { color: 'red', text: '失败' },
                  cancelled: { color: 'default', text: '已取消' },
                };
                const info = map[s] || { color: 'default', text: s };
                return <Tag color={info.color}>{info.text}</Tag>;
              },
            },
            { title: '通过/失败', width: 130,
              render: (_, r: any) => (
                <Space size={4}>
                  <Tag color="green">{r.success_count || 0}</Tag>
                  <Tag color="red">{r.failed_count || 0}</Tag>
                </Space>
              ),
            },
            { title: '耗时', dataIndex: 'duration', width: 110,
              render: (d: number) => formatDuration(d),
            },
            { title: '执行时间', dataIndex: 'start_time', width: 180, render: (t: string) => t || '-' },
            { title: '操作', width: 200, fixed: 'right' as const,
              render: (_: any, r: any) => (
                <Space>
                  <Tooltip title="查看详情">
                    <Button size="small" type="link" icon={<EyeOutlined />} onClick={() => navigate(`/report/${r.id}`)}>详情</Button>
                  </Tooltip>
                  <Tooltip title="查看HTML报告">
                    <Button size="small" icon={<FileTextOutlined />} onClick={() => window.open(`/api/executions/${r.id}/report?format=html`, '_blank')} />
                  </Tooltip>
                  <Tooltip title="下载Excel">
                    <Button size="small" icon={<DownloadOutlined />} onClick={() => window.open(`/api/executions/${r.id}/report?format=excel`, '_blank')} />
                  </Tooltip>
                </Space>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}
