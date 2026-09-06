/**
 * 注册页面
 */
import { useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Form, Input, Button, message } from 'antd';
import { getPublicAuthConfig, register, sendSmsCode, type CaptchaPayload } from '../../services/auth';
import AuthCaptcha, { loadCaptcha } from './AuthCaptcha';

export default function RegisterPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [smsLoading, setSmsLoading] = useState(false);
  const [captcha, setCaptcha] = useState<CaptchaPayload | null>(null);
  const [form] = Form.useForm();

  const refreshCaptcha = async () => {
    const next = await loadCaptcha();
    setCaptcha(next);
    form.setFieldValue('captcha_code', '');
  };

  useEffect(() => {
    getPublicAuthConfig()
      .then((cfg) => {
        if (!cfg.allow_register) {
          message.warning('当前已关闭开放注册');
          navigate('/auth/login', { replace: true });
        }
      })
      .catch(() => navigate('/auth/login', { replace: true }));
    refreshCaptcha().catch(() => message.error('验证码加载失败'));
  }, [navigate]);

  const onSendSms = async () => {
    const phone = form.getFieldValue('phone');
    const captchaCode = form.getFieldValue('captcha_code');
    if (!phone) {
      message.warning('请先填写手机号');
      return;
    }
    if (!captchaCode) {
      message.warning('请先填写图形验证码');
      return;
    }
    setSmsLoading(true);
    try {
      const sent = await sendSmsCode({
        phone,
        purpose: 'register',
        captcha_id: captcha?.captcha_id || '',
        captcha_code: captchaCode,
      });
      if (sent.debug_code) {
        message.success(`验证码已发送（演示）：${sent.debug_code}`);
        form.setFieldValue('sms_code', sent.debug_code);
      } else {
        message.success('验证码已发送');
      }
      refreshCaptcha();
    } catch (err: any) {
      message.error(err?.response?.data?.detail || err.message || '发送失败');
      refreshCaptcha();
    } finally {
      setSmsLoading(false);
    }
  };

  const onFinish = async (values: any) => {
    setLoading(true);
    try {
      const result = await register({
        username: values.username,
        password: values.password,
        phone: values.phone,
        sms_code: values.sms_code,
        captcha_id: captcha?.captcha_id || '',
        captcha_code: values.captcha_code,
        email: values.email,
        display_name: values.display_name,
      });
      if (result.pending_approval) {
        message.success('注册成功，请等待管理员审批后再登录');
        navigate('/auth/login', { replace: true });
        return;
      }
      message.success('注册成功');
      navigate('/', { replace: true });
    } catch (err: any) {
      message.error(err?.response?.data?.detail || err.message || '注册失败');
      refreshCaptcha();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="auth-brand">AI 自动化测试</div>
        <div className="auth-title">创建账号</div>
        <div className="auth-subtitle">手机号验证后即可使用</div>

        <Form form={form} name="register" onFinish={onFinish} autoComplete="off" layout="vertical" requiredMark={false}>
          <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }, { min: 3, message: '用户名至少3个字符' }]}>
            <Input placeholder="用户名" />
          </Form.Item>
          <Form.Item name="phone" label="手机号" rules={[{ required: true, message: '请输入手机号' }, { pattern: /^1[3-9]\d{9}$/, message: '请输入有效手机号' }]}>
            <Input placeholder="11 位手机号" />
          </Form.Item>
          <Form.Item name="captcha_code" label="图形验证码" rules={[{ required: true, message: '请输入图形验证码' }]}>
            <AuthCaptcha captcha={captcha} onRefresh={refreshCaptcha} />
          </Form.Item>
          <Form.Item name="sms_code" label="短信验证码" rules={[{ required: true, message: '请输入短信验证码' }]}>
            <Input
              placeholder="6 位验证码"
              addonAfter={(
                <Button type="link" size="small" loading={smsLoading} onClick={onSendSms} style={{ padding: 0 }}>
                  获取验证码
                </Button>
              )}
            />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }, { min: 8, message: '密码至少8个字符' }]}>
            <Input.Password placeholder="至少 8 位" />
          </Form.Item>
          <Form.Item
            name="confirmPassword"
            label="确认密码"
            dependencies={['password']}
            rules={[
              { required: true, message: '请确认密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('password') === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error('两次输入的密码不一致'));
                },
              }),
            ]}
          >
            <Input.Password placeholder="再次输入密码" />
          </Form.Item>
          <Form.Item name="email" label="邮箱">
            <Input placeholder="可选" />
          </Form.Item>
          <Form.Item name="display_name" label="显示名称">
            <Input placeholder="可选" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button type="primary" htmlType="submit" loading={loading} block>
              创建
            </Button>
          </Form.Item>
        </Form>

        <div style={{ textAlign: 'center', marginTop: 24, fontSize: 13, color: '#6b6560' }}>
          已有账号？ <Link to="/auth/login" style={{ color: '#1c1c1c' }}>返回登录</Link>
        </div>
      </div>
    </div>
  );
}
