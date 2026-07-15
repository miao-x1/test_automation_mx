import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Row, Col, Statistic, Button, Table, Tag, Spin, message, Typography, Space } from 'antd';
import {
  RocketOutlined, CheckCircleOutlined, CloseCircleOutlined, FileTextOutlined,
  CodeOutlined, ExperimentOutlined, PlayCircleOutlined,
} from '@ant-design/icons';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from 'recharts';
import request from '@/services/request';

const { Title, Text } = Typography;

export default function DashboardPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<any>({});
  const [recentTasks, setRecentTasks] = useState<any[]>([]);
  const [failedTasks, setFailedTasks] = useState<any[]>([]);
  const [trendData, setTrendData] = useState<any[]>([]);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [statsRes, recentRes, trendRes] = await Promise.all([
        request.get('/dashboard/stats'),
        request.get('/dashboard/recent'),
        request.get('/dashboard/trend', { params: { days: 7 } }).catch(() => null),
      ]);
      const sd = statsRes.data || statsRes;
      if (sd) setStats(sd);
      const rd = recentRes.data || recentRes;
      if (rd?.items) {
        setRecentTasks(rd.items.slice(0, 5));
        setFailedTasks(rd.items.filter((t: any) => t.status === 'failed').slice(0, 3));
      }
      if (trendRes) {
        const td = trendRes.data || trendRes;
        if (Array.isArray(td) && td.length > 0) setTrendData(td);
      }
    } catch {
      message.error('加载统计数据失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  return (
    <div>
      {/* 顶部欢迎区 */}
      <Card style={{ marginBottom: 16, background: 'linear-gradient(135deg, #1677ff 0%, #4096ff 100%)', border: 'none' }}>
        <Row align="middle" justify="space-between">
          <Col>
            <Title level={3} style={{ color: '#fff', margin: 0 }}>欢迎使用 AI 自动化测试平台</Title>
            <Text style={{ color: 'rgba(255,255,255,0.85)' }}>输入测试需求，AI 自动完成用例生成、脚本编写和自动执行</Text>
          </Col>
          <Col>
              <Button
                type="primary"
                size="large"
                icon={<RocketOutlined />}
                onClick={() => navigate('/task/create')}
                style={{ background: '#fff', color: '#1677ff', border: 'none', fontWeight: 600, height: 48, padding: '0 32px' }}
              >
                开始智能测试
              </Button>
          </Col>
        </Row>
      </Card>

      <Spin spinning={loading}>
        {/* 统计卡片 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card><Statistic title="测试任务" value={stats.task_count || 0} prefix={<FileTextOutlined />} /></Card>
          </Col>
          <Col span={6}>
            <Card><Statistic title="AI生成用例" value={stats.case_count || 0} prefix={<ExperimentOutlined />} valueStyle={{ color: '#52c41a' }} /></Card>
          </Col>
          <Col span={6}>
            <Card><Statistic title="AI生成脚本" value={stats.script_count || 0} prefix={<CodeOutlined />} valueStyle={{ color: '#1677ff' }} /></Card>
          </Col>
          <Col span={6}>
            <Card><Statistic title="执行成功率" value={stats.success_rate || 0} suffix="%" prefix={<CheckCircleOutlined />} valueStyle={{ color: stats.success_rate >= 80 ? '#52c41a' : '#faad14' }} /></Card>
          </Col>
        </Row>

        {/* 趋势图 */}
        {trendData.length > 0 && (
          <Card title={<Space><PlayCircleOutlined style={{ color: '#1677ff' }} /> 7天任务趋势</Space>} style={{ marginBottom: 16 }}>
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={trendData}>
                <defs>
                  <linearGradient id="colorTasks" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#1677ff" stopOpacity={0.6} />
                    <stop offset="95%" stopColor="#1677ff" stopOpacity={0.05} />
                  </linearGradient>
                  <linearGradient id="colorExec" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#52c41a" stopOpacity={0.6} />
                    <stop offset="95%" stopColor="#52c41a" stopOpacity={0.05} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={{ fontSize: 12 }} tickFormatter={(v: string) => v.slice(5)} />
                <YAxis />
                <Tooltip />
                <Legend />
                <Area type="monotone" dataKey="tasks" name="任务数" stroke="#1677ff" fill="url(#colorTasks)" />
                <Area type="monotone" dataKey="exec_count" name="执行数" stroke="#52c41a" fill="url(#colorExec)" />
              </AreaChart>
            </ResponsiveContainer>
          </Card>
        )}

        <Row gutter={16}>
          {/* 最近任务 */}
          <Col span={16}>
            <Card title="最近任务" extra={<Button type="link" onClick={() => navigate('/task')}>查看全部</Button>}>
              <Table dataSource={recentTasks} rowKey="id" size="small" pagination={false}
                columns={[
                  { title: 'ID', dataIndex: 'id', width: 60 },
                  { title: '任务名称', dataIndex: 'task_name', ellipsis: true },
                  { title: '状态', dataIndex: 'status', width: 100, render: (s: string) => {
                    const map: Record<string, { color: string; text: string }> = {
                      pending: { color: 'orange', text: '等待中' },
                      running: { color: 'blue', text: '执行中' },
                      success: { color: 'green', text: '成功' },
                      failed: { color: 'red', text: '失败' },
                      completed: { color: 'green', text: '已完成' },
                    };
                    const info = map[s] || { color: 'default', text: s };
                    return <Tag color={info.color}>{info.text}</Tag>;
                  }},
                  { title: '创建时间', dataIndex: 'created_at', width: 180, render: (t: string) => t || '-' },
                  { title: '操作', width: 80, render: (_: any, r: any) => (
                    <Button type="link" size="small" onClick={() => navigate(`/task/${r.id}`)}>详情</Button>
                  )},
                ]}
              />
            </Card>
          </Col>

          {/* 失败任务 */}
          <Col span={8}>
            <Card title={<Space><CloseCircleOutlined style={{ color: '#ff4d4f' }} /> 失败任务</Space>} extra={<Button type="link" onClick={() => navigate('/report')}>查看报告</Button>}>
              {failedTasks.length === 0 ? (
                <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>
                  <CheckCircleOutlined style={{ fontSize: 32, color: '#52c41a' }} />
                  <p style={{ marginTop: 8 }}>暂无失败任务</p>
                </div>
              ) : (
                <Table dataSource={failedTasks} rowKey="id" size="small" pagination={false}
                  columns={[
                    { title: '任务', dataIndex: 'task_name', ellipsis: true },
                    { title: '操作', width: 80, render: (_: any, r: any) => (
                      <Button type="link" size="small" danger onClick={() => navigate(`/report/${r.id}`)}>查看</Button>
                    )},
                  ]}
                />
              )}
            </Card>
          </Col>
        </Row>
      </Spin>
    </div>
  );
}
