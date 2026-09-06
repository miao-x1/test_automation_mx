import { useEffect, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { Form, Input, Tabs, message, Button } from 'antd';
import request from '@/services/request';
import ProfilePage from '../auth/ProfilePage';
import Settings from '../settings/Settings';
import AdminEnvironments from '../admin/AdminEnvironments';
import './product.css';

const TAB_PATH: Record<string, string> = {
  profile: '/profile',
  ai: '/profile/ai',
  env: '/profile/env',
  security: '/profile/security',
};

function tabFromLocation(pathname: string, searchTab: string | null): string {
  if (pathname.endsWith('/ai')) return 'ai';
  if (pathname.endsWith('/env')) return 'env';
  if (pathname.endsWith('/security')) return 'security';
  if (searchTab && searchTab in TAB_PATH) return searchTab;
  return 'profile';
}

export default function AccountHubPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const tab = tabFromLocation(location.pathname, params.get('tab'));

  return (
    <div className="product-shell">
      <div className="product-hero">
        <h1>个人中心</h1>
        <p>账号、AI 配置和执行环境都在左侧栏进入，页面框架不会换。</p>
      </div>
      <div className="product-card" style={{ paddingTop: 8 }}>
        <Tabs
          activeKey={tab}
          onChange={(key) => navigate(TAB_PATH[key] || '/profile')}
          items={[
            { key: 'profile', label: '账号信息', children: <ProfilePage embedded /> },
            { key: 'ai', label: 'AI 配置', children: <Settings /> },
            { key: 'env', label: '执行环境', children: <AdminEnvironments /> },
            { key: 'security', label: '安全设置', children: <SecurityPanel /> },
          ]}
        />
      </div>
    </div>
  );
}

function SecurityPanel() {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    form.resetFields();
  }, [form]);

  return (
    <div>
      <p className="product-note" style={{ marginBottom: 16 }}>修改登录密码。</p>
      <Form
        form={form}
        layout="vertical"
        style={{ maxWidth: 420 }}
        onFinish={async (values) => {
          setSaving(true);
          try {
            const res: any = await request.put('/auth/password', {
              old_password: values.old_password,
              new_password: values.new_password,
            });
            if (res.code === 200) {
              message.success('密码已修改');
              form.resetFields();
            } else {
              message.error(res.message || '修改失败');
            }
          } catch {
            message.error('修改失败');
          } finally {
            setSaving(false);
          }
        }}
      >
        <Form.Item name="old_password" label="当前密码" rules={[{ required: true, message: '请输入当前密码' }]}>
          <Input.Password />
        </Form.Item>
        <Form.Item name="new_password" label="新密码" rules={[{ required: true, message: '请输入新密码' }, { min: 6, message: '至少 6 位' }]}>
          <Input.Password />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={saving}>保存</Button>
      </Form>
    </div>
  );
}
