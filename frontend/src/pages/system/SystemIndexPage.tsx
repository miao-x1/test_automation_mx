import { useNavigate } from 'react-router-dom';
import { Card, Row, Col, Typography } from 'antd';
import { UserOutlined, ApartmentOutlined, FolderOutlined, GlobalOutlined, DatabaseOutlined, SettingOutlined, RobotOutlined } from '@ant-design/icons';

const { Title, Text } = Typography;

const modules = [
  { key: '/system/users', title: '用户管理', desc: '管理系统用户账号和权限分配', icon: <UserOutlined style={{ fontSize: 28, color: '#1c1c1c' }} /> },
  { key: '/system/roles', title: '角色权限', desc: '管理角色和权限策略', icon: <ApartmentOutlined style={{ fontSize: 28, color: '#1c1c1c' }} /> },
  { key: '/system/projects', title: '项目管理', desc: '管理测试项目和项目配置', icon: <FolderOutlined style={{ fontSize: 28, color: '#1c1c1c' }} /> },
  { key: '/system/environments', title: '环境配置', desc: '管理测试环境URL、变量和密钥', icon: <GlobalOutlined style={{ fontSize: 28, color: '#1c1c1c' }} /> },
  { key: '/system/datasources', title: '数据源', desc: '管理数据库连接和API端点', icon: <DatabaseOutlined style={{ fontSize: 28, color: '#1c1c1c' }} /> },
  { key: '/system/settings', title: '系统设置', desc: '系统全局参数和功能开关', icon: <SettingOutlined style={{ fontSize: 28, color: '#1c1c1c' }} /> },
  { key: '/system/ai', title: 'AI 能力', desc: 'Agent 运行时、监控、会话管理', icon: <RobotOutlined style={{ fontSize: 28, color: '#1c1c1c' }} /> },
];

export default function SystemIndexPage() {
  const navigate = useNavigate();
  return (
    <div>
      <Title level={3}>系统管理</Title>
      <Row gutter={[16, 16]}>
        {modules.map((m) => (
          <Col span={8} key={m.key}>
            <Card hoverable onClick={() => navigate(m.key)} style={{ height: '100%' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                {m.icon}
                <div>
                  <Title level={5} style={{ margin: 0 }}>{m.title}</Title>
                  <Text type="secondary" style={{ fontSize: 12 }}>{m.desc}</Text>
                </div>
              </div>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  );
}
