import { useState, useEffect, useCallback } from 'react';
import { Card, Form, Input, Switch, Button, Spin, message } from 'antd';
import { SettingOutlined } from '@ant-design/icons';
import { PageHeader } from '../../components/UI';
import request from '../../services/request';

interface SettingsData {
  backend_url?: string;
  debug_mode?: boolean;
  qwen_api_key?: string;
  openai_api_key?: string;
}

export default function AdminSettings() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const fetchSettings = useCallback(async () => {
    setLoading(true);
    try {
      const res: any = await request.get('/admin/settings');
      const data: SettingsData = res?.data || {};
      form.setFieldsValue({
        backend_url: data.backend_url,
        debug_mode: !!data.debug_mode,
        qwen_api_key: data.qwen_api_key,
        openai_api_key: data.openai_api_key,
      });
    } catch {
      message.error('获取配置失败');
    } finally {
      setLoading(false);
    }
  }, [form]);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      const res: any = await request.put('/admin/settings', values);
      if (res?.code === 200) {
        message.success('保存成功');
      } else {
        message.error(res?.message || '保存失败');
      }
    } catch (e: any) {
      if (e?.errorFields) return; // 表单校验未通过
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <PageHeader title="系统配置" subtitle="系统全局参数和功能开关" icon={<SettingOutlined />} />
      <Card>
        <Spin spinning={loading}>
          <Form form={form} layout="vertical" style={{ maxWidth: 600 }}>
            <Form.Item name="backend_url" label="后端 URL" rules={[{ required: true, message: '请输入后端 URL' }]}>
              <Input placeholder="http://localhost:8000" />
            </Form.Item>
            <Form.Item name="debug_mode" label="调试模式" valuePropName="checked">
              <Switch checkedChildren="开" unCheckedChildren="关" />
            </Form.Item>
            <Form.Item name="qwen_api_key" label="Qwen API Key">
              <Input.Password placeholder="通义千问 API Key" />
            </Form.Item>
            <Form.Item name="openai_api_key" label="OpenAI API Key">
              <Input.Password placeholder="OpenAI API Key" />
            </Form.Item>
            <Form.Item>
              <Button type="primary" loading={saving} onClick={handleSave}>
                保存配置
              </Button>
            </Form.Item>
          </Form>
        </Spin>
      </Card>
    </div>
  );
}
