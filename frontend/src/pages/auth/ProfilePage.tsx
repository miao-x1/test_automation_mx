/**
 * 个人中心页面
 *
 * 展示：用户信息（可编辑）、头像上传、统计概览（可点击跳转）、修改密码
 * 后端 API：
 *   GET    /api/auth/me            - 获取当前用户信息
 *   PUT    /api/auth/profile       - 更新用户资料
 *   PUT    /api/auth/password      - 修改密码
 *   POST   /api/auth/avatar        - 上传头像
 *   GET    /api/auth/profile/stats - 个人统计
 */
import { useEffect, useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Card, Tag, Statistic, Row, Col, Spin, Typography, Avatar,
  Button, Form, Input, Modal, message, Space, List,
} from 'antd';
import {
  UserOutlined, FileTextOutlined, DatabaseOutlined,
  ThunderboltOutlined, EditOutlined, LockOutlined,
  CheckCircleOutlined, CloseCircleOutlined, BarChartOutlined,
  CameraOutlined, RightOutlined,
} from '@ant-design/icons';
import { getStoredUser, saveUser, UserInfo } from '../../services/auth';
import request from '../../services/request';

const { Title, Text } = Typography;

interface UserStats {
  tasks: { total: number; completed: number; failed: number };
  requirements: { total: number };
  executions: { total: number; success: number; pass_rate: number };
  knowledge: { elements: number; scripts: number };
  feedback: { avg_score: number };
}

export default function ProfilePage({ embedded = false }: { embedded?: boolean }) {
  const navigate = useNavigate();
  const [user, setUser] = useState<UserInfo | null>(getStoredUser());
  const [stats, setStats] = useState<UserStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [editLoading, setEditLoading] = useState(false);
  const [passwordModalVisible, setPasswordModalVisible] = useState(false);
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [avatarUploading, setAvatarUploading] = useState(false);
  const [editForm] = Form.useForm();
  const [passwordForm] = Form.useForm();
  const avatarInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadStats();
    loadUserInfo();
  }, []);

  const loadUserInfo = async () => {
    try {
      const res: any = await request.get('/auth/me');
      if (res.code === 200 && res.data) {
        setUser(res.data);
        saveUser(res.data);
      }
    } catch { /* ignore */ }
  };

  const loadStats = async () => {
    setLoading(true);
    try {
      const res: any = await request.get('/auth/profile/stats');
      if (res.code === 200 && res.data) {
        setStats(res.data);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  const handleEditProfile = async () => {
    try {
      const values = await editForm.validateFields();
      setEditLoading(true);
      const res: any = await request.put('/auth/profile', values);
      if (res.code === 200) {
        message.success('资料更新成功');
        setUser(res.data);
        saveUser(res.data);
        setEditModalVisible(false);
      } else {
        message.error(res.message || '更新失败');
      }
    } catch (err: any) {
      if (err?.errorFields) return;
      message.error('更新失败');
    } finally {
      setEditLoading(false);
    }
  };

  const handleChangePassword = async () => {
    try {
      const values = await passwordForm.validateFields();
      setPasswordLoading(true);
      const res: any = await request.put('/auth/password', {
        old_password: values.old_password,
        new_password: values.new_password,
      });
      if (res.code === 200) {
        message.success('密码修改成功');
        setPasswordModalVisible(false);
        passwordForm.resetFields();
      } else {
        message.error(res.message || '修改失败');
      }
    } catch (err: any) {
      if (err?.errorFields) return;
      message.error('修改失败');
    } finally {
      setPasswordLoading(false);
    }
  };

  const handleAvatarUpload = async (file: File) => {
    setAvatarUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const response = await fetch('/api/auth/avatar', {
        method: 'POST',
        body: formData,
        credentials: 'include',
      });
      if (!response.ok) throw new Error('头像上传失败');
      const res = await response.json();
      if (res.code === 200) {
        message.success('头像更新成功');
        setUser(res.data);
        saveUser(res.data);
      } else {
        message.error(res.message || '头像上传失败');
      }
    } catch {
      message.error('头像上传失败');
    } finally {
      setAvatarUploading(false);
    }
  };

  const openEditModal = () => {
    editForm.setFieldsValue({
      display_name: user?.display_name || '',
      email: user?.email || '',
    });
    setEditModalVisible(true);
  };

  // 统计卡片可点击跳转
  const statCards = [
    {
      title: '我的任务',
      value: stats?.tasks?.total || 0,
      icon: <FileTextOutlined />,
      route: '/assets?tab=tasks',
      tags: [
        { color: 'success', text: `完成 ${stats?.tasks?.completed || 0}`, icon: <CheckCircleOutlined /> },
        { color: 'error', text: `失败 ${stats?.tasks?.failed || 0}`, icon: <CloseCircleOutlined /> },
      ],
    },
    {
      title: '测试记录',
      value: stats?.requirements?.total || 0,
      icon: <BarChartOutlined />,
      route: '/assets?tab=tasks',
      tags: [],
    },
    {
      title: '我的执行',
      value: stats?.executions?.total || 0,
      icon: <ThunderboltOutlined />,
      route: '/assets?tab=reports',
      tags: [
        {
          color: (stats?.executions?.pass_rate || 0) >= 80 ? 'success' : 'error',
          text: `通过率 ${stats?.executions?.pass_rate || 0}%`,
        },
      ],
    },
    {
      title: '测试用例',
      value: stats?.requirements?.total || 0,
      icon: <DatabaseOutlined />,
      route: '/assets?tab=cases',
      tags: [],
    },
  ];

  // 个人信息菜单项
  const profileMenuItems = [
    { label: '用户名', value: `@${user?.username || ''}`, icon: <UserOutlined /> },
    { label: '邮箱', value: user?.email || '未设置', icon: <EditOutlined />, editable: true },
    { label: '显示名称', value: user?.display_name || '未设置', icon: <UserOutlined />, editable: true },
    { label: '角色', value: user?.role === 'admin' ? '管理员' : '普通用户', icon: <UserOutlined />, tag: true },
    { label: '注册时间', value: user?.created_at?.split('T')[0] || '-', icon: <FileTextOutlined /> },
  ];

  return (
    <div className="product-shell">
      <div className="product-hero">
        <h1>个人中心</h1>
        <p>账号资料、密码和你的测试统计。团队和项目请到工作空间管理。</p>
      </div>

      <Spin spinning={loading}>
        {/* 用户信息卡片 */}
        <Card style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
            {/* 头像：点击可上传 */}
            <div
              style={{ position: 'relative', cursor: 'pointer', flexShrink: 0 }}
              onClick={() => avatarInputRef.current?.click()}
            >
              <Avatar size={80} icon={<UserOutlined />} src={user?.avatar} />
              <div style={{
                position: 'absolute', bottom: 0, right: 0,
                background: '#1c1c1c', borderRadius: '50%', width: 24, height: 24,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                border: '2px solid #fff',
              }}>
                <CameraOutlined style={{ color: '#fff', fontSize: 12 }} />
              </div>
              {avatarUploading && (
                <div style={{
                  position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
                  background: 'rgba(0,0,0,0.4)', borderRadius: '50%',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  <Spin size="small" />
                </div>
              )}
              <input
                ref={avatarInputRef}
                type="file"
                accept="image/jpeg,image/png,image/gif,image/webp"
                style={{ display: 'none' }}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) {
                    if (file.size > 2 * 1024 * 1024) {
                      message.error('头像文件不能超过 2MB');
                      return;
                    }
                    handleAvatarUpload(file);
                  }
                  e.target.value = '';
                }}
              />
            </div>
            <div style={{ flex: 1 }}>
              <Title level={4} style={{ marginBottom: 4 }}>
                {user?.display_name || user?.username || '未知用户'}
              </Title>
              <Text type="secondary" style={{ fontSize: 12 }}>
                点击头像可更换
              </Text>
            </div>
            <Space direction="vertical">
              <Button type="primary" icon={<EditOutlined />} onClick={openEditModal}>
                编辑资料
              </Button>
              {!embedded && (
                <Button icon={<LockOutlined />} onClick={() => setPasswordModalVisible(true)}>
                  修改密码
                </Button>
              )}
            </Space>
          </div>
        </Card>

        {/* 个人信息列表（可点击查看/编辑） */}
        <Card title="个人信息" style={{ marginBottom: 24 }} size="small">
          <List
            dataSource={profileMenuItems}
            renderItem={(item) => (
              <List.Item
                style={{ cursor: item.editable ? 'pointer' : 'default', padding: '12px 0' }}
                actions={item.editable ? [
                  <Button type="link" size="small" icon={<EditOutlined />} onClick={openEditModal}>
                    修改
                  </Button>,
                ] : undefined}
              >
                <List.Item.Meta
                  avatar={<span style={{ color: '#8c8c8c', fontSize: 16 }}>{item.icon}</span>}
                  title={<Text type="secondary" style={{ fontSize: 12 }}>{item.label}</Text>}
                  description={
                    item.tag
                      ? <Tag color={user?.role === 'admin' ? 'red' : 'blue'}>{item.value}</Tag>
                      : <Text strong>{item.value}</Text>
                  }
                />
              </List.Item>
            )}
          />
        </Card>

        {/* 统计卡片（可点击跳转） */}
        <Card title="数据统计" size="small">
          <Row gutter={16}>
            {statCards.map((card) => (
              <Col span={6} key={card.title}>
                <Card
                  hoverable
                  onClick={() => navigate(card.route)}
                  style={{ cursor: 'pointer' }}
                  bodyStyle={{ padding: 20 }}
                >
                  <Statistic title={card.title} value={card.value} prefix={card.icon} />
                  {card.tags.length > 0 && (
                    <div style={{ marginTop: 8 }}>
                      {card.tags.map((t, i) => (
                        <Tag key={i} color={t.color}>
                          {'icon' in t ? t.icon : null} {t.text}
                        </Tag>
                      ))}
                    </div>
                  )}
                  <div style={{ marginTop: 8, textAlign: 'right' }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      查看详情 <RightOutlined style={{ fontSize: 10 }} />
                    </Text>
                  </div>
                </Card>
              </Col>
            ))}
          </Row>
        </Card>
      </Spin>

      {/* 编辑资料弹窗 */}
      <Modal
        title="编辑个人资料"
        open={editModalVisible}
        onOk={handleEditProfile}
        onCancel={() => setEditModalVisible(false)}
        confirmLoading={editLoading}
        okText="保存"
        cancelText="取消"
      >
        <Form form={editForm} layout="vertical">
          <Form.Item name="display_name" label="显示名称" rules={[{ max: 100, message: '最多100个字符' }]}>
            <Input placeholder="输入显示名称" />
          </Form.Item>
          <Form.Item
            name="email"
            label="邮箱"
            rules={[
              { type: 'email', message: '请输入有效的邮箱地址' },
            ]}
          >
            <Input placeholder="输入邮箱地址" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 修改密码弹窗 */}
      <Modal
        title="修改密码"
        open={passwordModalVisible}
        onOk={handleChangePassword}
        onCancel={() => { setPasswordModalVisible(false); passwordForm.resetFields(); }}
        confirmLoading={passwordLoading}
        okText="确认修改"
        cancelText="取消"
      >
        <Form form={passwordForm} layout="vertical">
          <Form.Item
            name="old_password"
            label="旧密码"
            rules={[{ required: true, message: '请输入旧密码' }]}
          >
            <Input.Password placeholder="输入旧密码" />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 6, message: '密码至少6个字符' },
            ]}
          >
            <Input.Password placeholder="输入新密码" />
          </Form.Item>
          <Form.Item
            name="confirm_password"
            label="确认新密码"
            dependencies={['new_password']}
            rules={[
              { required: true, message: '请确认新密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('new_password') === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error('两次输入的密码不一致'));
                },
              }),
            ]}
          >
            <Input.Password placeholder="再次输入新密码" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
