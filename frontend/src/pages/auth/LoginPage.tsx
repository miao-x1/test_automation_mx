/**
 * 登录页面
 */
import { useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Form, Input, Button, message } from 'antd';
import { getPublicAuthConfig, login, saveUser, type PublicAuthConfig } from '../../services/auth';
import request from '../../services/request';

export default function LoginPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [cfg, setCfg] = useState<PublicAuthConfig | null>(null);
  const [form] = Form.useForm();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const next = await getPublicAuthConfig();
        if (!cancelled) setCfg(next);
      } catch {
        if (!cancelled) setCfg({
          allow_register: false,
          register_require_approval: false,
          captcha_required: false,
          sms_provider: 'console',
          sms_echo: false,
        });
      }
      try {
        setLoading(true);
        const res: any = await request.post('/auth/quick-enter');
        if (cancelled) return;
        if (res?.code === 200 && res?.data?.user) {
          saveUser(res.data.user);
          navigate('/', { replace: true });
          return;
        }
      } catch {
        // 快速进入失败时再走账号密码
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [navigate]);

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true);
    try {
      await login({
        username: values.username,
        password: values.password,
        captcha_id: '',
        captcha_code: '',
      });
      message.success('登录成功');
      navigate('/', { replace: true });
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.response?.data?.message || err.message || '登录失败，请检查用户名和密码';
      message.error(detail);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="auth-brand">AI 自动化测试</div>
        <div className="auth-title">登录</div>
        <div className="auth-subtitle">输入页面地址，开始测试</div>

        <Form form={form} name="login" onFinish={onFinish} autoComplete="off" layout="vertical" requiredMark={false}>
          <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input placeholder="用户名" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password placeholder="密码" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0, marginTop: 8 }}>
            <Button type="primary" htmlType="submit" loading={loading} block>
              进入
            </Button>
          </Form.Item>
        </Form>

        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 24, fontSize: 13, color: '#6b6560' }}>
          <Link to="/auth/forgot-password" style={{ color: '#1c1c1c' }}>忘记密码</Link>
          {cfg?.allow_register && (
            <Link to="/auth/register" style={{ color: '#1c1c1c' }}>创建账号</Link>
          )}
        </div>
      </div>
    </div>
  );
}
