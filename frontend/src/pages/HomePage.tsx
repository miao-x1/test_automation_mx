/**
 * 首页 - 统一测试平台概览
 */
import { useEffect, useState } from 'react';
import { Card, Row, Col, Statistic, Typography, List, Tag, Spin, Space, message } from 'antd';
import {
  RobotOutlined,
  UnorderedListOutlined,
  ThunderboltOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  FileTextOutlined,
  BugOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import request from '../services/request';
import { getStoredUser } from '../services/auth';

const { Title, Text } = Typography;

interface DashboardStats {
  tasks: {
    total: number;
    completed: number;
    failed: number;
    pending: number;
    success_rate: number;
  };
  scripts: {
    total: number;
  };
  executions: {
    total: number;
    success: number;
    failed: number;
    avg_duration: number;
  };
  knowledge_base: {
    total: number;
    elements: number;
    cases: number;
    scripts: number;
  };
  graph: {
    total: number;
    pages: number;
    elements: number;
    cases: number;
    scripts: number;
    relationships: number;
  };
  feedback: {
    total: number;
    avg_score: number;
  };
}

interface RecentTask {
  id: number;
  requirement: string;
  status: string;
  intent: string | null;
  script_source: string | null;
  created_at: string | null;
  duration: number | null;
}

export default function HomePage() {
  const navigate = useNavigate();
  const user = getStoredUser();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [recentTasks, setRecentTasks] = useState<RecentTask[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadStats();
  }, []);

  const loadStats = async () => {
    setLoading(true);
    try {
      const [statsRes, recentRes]: any[] = await Promise.all([
        request.get('/dashboard/stats'),
        request.get('/dashboard/recent', { params: { limit: 10 } }),
      ]);

      if (statsRes?.code === 200 && statsRes?.data) {
        setStats(statsRes.data);
      }

      if (recentRes?.code === 200 && recentRes?.data) {
        setRecentTasks(recentRes.data);
      }
    } catch {
      message.error('加载统计数据失败');
    } finally {
      setLoading(false);
    }
  };

  const statusColor: Record<string, string> = {
    pending: 'default',
    processing: 'processing',
    completed: 'success',
    failed: 'error',
    success: 'success',
  };

  const statusLabel: Record<string, string> = {
    pending: '待处理',
    processing: '处理中',
    completed: '已完成',
    failed: '失败',
    success: '成功',
  };

  return (
    <div>
      <Title level={4}>
        欢迎回来，{user?.display_name || user?.username || '用户'}
      </Title>
      <Text type="secondary">统一测试平台 - Unified Testing Platform</Text>

      <Spin spinning={loading}>
        <Row gutter={16} style={{ marginTop: 24 }}>
          <Col span={6}>
            <Card hoverable onClick={() => navigate('/requirement')}>
              <Statistic
                title="需求"
                value={stats?.tasks?.total || 0}
                prefix={<RobotOutlined />}
                valueStyle={{ color: '#722ed1' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card hoverable onClick={() => navigate('/execution')}>
              <Statistic
                title="执行"
                value={stats?.executions?.total || 0}
                prefix={<ThunderboltOutlined />}
                valueStyle={{ color: '#fa8c16' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card hoverable onClick={() => navigate('/execution')}>
              <Statistic
                title="成功率"
                value={stats?.tasks?.success_rate || 0}
                suffix="%"
                prefix={(stats?.tasks?.success_rate || 0) >= 80 ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
                valueStyle={{ color: (stats?.tasks?.success_rate || 0) >= 80 ? '#3f8600' : '#cf1322' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card hoverable onClick={() => navigate('/execution/recent')}>
              <Statistic
                title="失败执行"
                value={stats?.executions?.failed || 0}
                prefix={<BugOutlined />}
                valueStyle={{ color: '#ff4d4f' }}
              />
            </Card>
          </Col>
        </Row>

        <Row gutter={16} style={{ marginTop: 16 }}>
          <Col span={6}>
            <Card>
              <Statistic
                title="脚本"
                value={stats?.scripts?.total || 0}
                prefix={<FileTextOutlined />}
                valueStyle={{ color: '#13c2c2' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="成功执行"
                value={stats?.executions?.success || 0}
                prefix={<CheckCircleOutlined />}
                valueStyle={{ color: '#52c41a' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="平均耗时"
                value={stats?.executions?.avg_duration || 0}
                suffix="秒"
                prefix={<UnorderedListOutlined />}
                valueStyle={{ color: '#1890ff' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="知识库"
                value={stats?.knowledge_base?.total || 0}
                prefix={<RobotOutlined />}
                valueStyle={{ color: '#722ed1' }}
              />
            </Card>
          </Col>
        </Row>

        <Row gutter={16} style={{ marginTop: 16 }}>
          <Col span={12}>
            <Card title="快速入口" size="small">
              <List
                size="small"
                dataSource={[
                  { title: '创建新需求', desc: '输入需求，AI自动生成测试', path: '/requirement' },
                  { title: '执行中心', desc: '查看所有执行记录', path: '/execution' },
                  { title: '缺陷分析', desc: '查看失败任务与根因', path: '/defect' },
                  { title: '系统设置', desc: '配置API密钥与服务', path: '/settings' },
                ]}
                renderItem={(item) => (
                  <List.Item
                    style={{ cursor: 'pointer' }}
                    onClick={() => navigate(item.path)}
                  >
                    <List.Item.Meta title={item.title} description={item.desc} />
                  </List.Item>
                )}
              />
            </Card>
          </Col>
          <Col span={12}>
            <Card title="最近任务" size="small">
              <List
                size="small"
                dataSource={recentTasks}
                locale={{ emptyText: '暂无任务' }}
                renderItem={(item) => (
                  <List.Item
                    style={{ cursor: 'pointer' }}
                    onClick={() => navigate(`/task/${item.id}`)}
                  >
                    <List.Item.Meta
                      title={item.requirement || `需求#${item.id}`}
                      description={
                        <Space>
                          <Tag color={statusColor[item.status] || 'default'}>
                            {statusLabel[item.status] || item.status}
                          </Tag>
                          {item.duration != null && <Text type="secondary">{item.duration}s</Text>}
                          {item.created_at && <Text type="secondary">{new Date(item.created_at).toLocaleString('zh-CN')}</Text>}
                        </Space>
                      }
                    />
                  </List.Item>
                )}
              />
            </Card>
          </Col>
        </Row>
      </Spin>
    </div>
  );
}
