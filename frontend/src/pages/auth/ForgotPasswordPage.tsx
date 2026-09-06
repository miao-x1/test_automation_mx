/**
 * 忘记密码
 */
import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Button, Form, Input, message } from 'antd';
import { resetPassword, sendSmsCode, type CaptchaPayload } from '../../services/auth';
import AuthCaptcha, { loadCaptcha } from './AuthCaptcha';

export default function ForgotPasswordPage() {
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
    refreshCaptcha().catch(() => message.error('验证码加载失败'));
  }, []);

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
        purpose: 'reset',
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
      await resetPassword({
        phone: values.phone,
        sms_code: values.sms_code,
        new_password: values.new_password,
        captcha_id: captcha?.captcha_id || '',
        captcha_code: values.captcha_code,
      });
      message.success('密码已重置，请登录');
      navigate('/auth/login', { replace: true });
    } catch (err: any) {
      message.error(err?.response?.data?.detail || err.message || '重置失败');
      refreshCaptcha();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="auth-brand">AI 自动化测试</div>
        <div className="auth-title">忘记密码</div>
        <div className="auth-subtitle">通过手机验证码设置新密码</div>

        <Form form={form} onFinish={onFinish} layout="vertical" requiredMark={false}>
          <Form.Item name="phone" label="手机号" rules={[{ required: true, message: '请输入手机号' }, { pattern: /^1[3-9]\d{9}$/, message: '请输入有效手机号' }]}>
            <Input placeholder="注册时使用的手机号" />
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
          <Form.Item name="new_password" label="新密码" rules={[{ required: true, message: '请输入新密码' }, { min: 8, message: '密码至少8个字符' }]}>
            <Input.Password placeholder="至少 8 位" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button type="primary" htmlType="submit" loading={loading} block>
              重置密码
            </Button>
          </Form.Item>
        </Form>

        <div style={{ textAlign: 'center', marginTop: 24, fontSize: 13, color: '#6b6560' }}>
          <Link to="/auth/login" style={{ color: '#1c1c1c' }}>返回登录</Link>
        </div>
      </div>
    </div>
  );
}
