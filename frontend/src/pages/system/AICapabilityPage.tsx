import { useNavigate } from 'react-router-dom';
import { Card, Row, Col, Typography, Tag, Space, Alert } from 'antd';
import { RobotOutlined, MonitorOutlined, MessageOutlined } from '@ant-design/icons';

const { Title, Text } = Typography;

const aiModules = [
  {
    key: '/system/ai/agent-runtime',
    title: 'Agent 运行时',
    desc: '查看和管理 AI Agent 的运行状态、任务分配和执行队列',
    icon: <RobotOutlined style={{ fontSize: 28, color: '#1677ff' }} />,
    tag: '运行时',
    tagColor: 'blue',
  },
  {
    key: '/system/ai/agent-monitor',
    title: 'Agent 监控',
    desc: '实时监控 Agent 执行状态、性能指标和资源使用情况',
    icon: <MonitorOutlined style={{ fontSize: 28, color: '#52c41a' }} />,
    tag: '监控',
    tagColor: 'green',
  },
  {
    key: '/system/ai/sessions',
    title: '会话管理',
    desc: '管理 AI 会话上下文、执行历史和制品存储',
    icon: <MessageOutlined style={{ fontSize: 28, color: '#722ed1' }} />,
    tag: '会话',
    tagColor: 'purple',
  },
];

export default function AICapabilityPage() {
  const navigate = useNavigate();
  return (
    <div>
      <Title level={3}><RobotOutlined /> AI 能力管理</Title>
      <Alert
        type="info"
        showIcon
        message="这是系统高级功能"
        description="以下功能面向系统管理员和开发者，普通测试用户无需关注。AI 能力在后台自动运行，支持测试需求的全流程自动化。"
        style={{ marginBottom: 16 }}
      />
      <Row gutter={[16, 16]}>
        {aiModules.map((m) => (
          <Col span={8} key={m.key}>
            <Card hoverable onClick={() => navigate(m.key)} style={{ height: '100%' }}>
              <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  {m.icon}
                  <Tag color={m.tagColor}>{m.tag}</Tag>
                </div>
                <div>
                  <Title level={5} style={{ margin: 0 }}>{m.title}</Title>
                  <Text type="secondary" style={{ fontSize: 12 }}>{m.desc}</Text>
                </div>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  );
}
