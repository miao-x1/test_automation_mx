import { Card, Row, Col, Typography } from 'antd';
import { useNavigate } from 'react-router-dom';
import { SettingOutlined, UserOutlined, SafetyOutlined, ProjectOutlined, CloudServerOutlined, DatabaseOutlined, CodeOutlined } from '@ant-design/icons';
import { PageHeader } from '../../components/UI';

const { Text } = Typography;

const modules = [
  { key: '/admin/users', title: '用户管理', icon: <UserOutlined />, desc: '管理系统用户账号和权限分配' },
  { key: '/admin/roles', title: '角色权限', icon: <SafetyOutlined />, desc: '管理角色和权限策略' },
  { key: '/admin/projects', title: '项目管理', icon: <ProjectOutlined />, desc: '管理测试项目和项目配置' },
  { key: '/admin/environments', title: '环境配置', icon: <CloudServerOutlined />, desc: '管理测试环境URL、变量和密钥' },
  { key: '/admin/settings', title: '系统配置', icon: <SettingOutlined />, desc: '系统全局参数和功能开关' },
  { key: '/admin/datasources', title: '数据源管理', icon: <DatabaseOutlined />, desc: '管理数据库连接和API端点' },
  { key: '/admin/scripts', title: '脚本仓库', icon: <CodeOutlined />, desc: '管理脚本模板和公共脚本库' },
];

export default function AdminIndex() {
  const navigate = useNavigate();
  return (
    <div>
      <PageHeader title="管理" subtitle="平台控制层：配置与资源管理" icon={<SettingOutlined />} />
      <Row gutter={[16, 16]}>
        {modules.map(m => (
          <Col xs={24} sm={12} lg={8} key={m.key}>
            <Card hoverable onClick={() => navigate(m.key)} style={{ textAlign: 'center', padding: '24px 16px' }}>
              <div style={{ fontSize: 36, color: '#1890ff', marginBottom: 12 }}>{m.icon}</div>
              <Text strong style={{ fontSize: 16 }}>{m.title}</Text>
              <div style={{ marginTop: 8, color: '#999' }}>{m.desc}</div>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  );
}
