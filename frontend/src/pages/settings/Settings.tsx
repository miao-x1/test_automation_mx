/**
 * 系统设置页面
 *
 * 功能：系统配置、环境变量、API密钥管理
 * 对接后端：GET /admin/settings, PUT /admin/settings
 */
import { useEffect, useState } from 'react';
import { Card, Typography, Form, Input, Button, Switch, Divider, message, Space, Spin } from 'antd';
import { SettingOutlined, KeyOutlined, CloudServerOutlined } from '@ant-design/icons';
import request from '@/services/request';

const { Title, Text } = Typography;

export default function Settings() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    setLoading(true);
    try {
      const res: any = await request.get('/admin/settings');
      if (res.code === 200 && res.data?.items?.[0]) {
        const config = res.data.items[0];
        form.setFieldsValue({
          backend_url: config.backend_url,
          debug_mode: config.debug_mode,
          qwen_api_key: config.qwen_api_key,
          openai_api_key: config.openai_api_key,
        });
      }
    } catch (err) {
      message.error('加载配置失败');
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      const res: any = await request.put('/admin/settings', values);
      if (res.code === 200) {
        message.success('设置已保存');
      } else {
        message.error(res.message || '保存失败');
      }
    } catch (err) {
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <Title level={3}><SettingOutlined /> 系统设置</Title>
      <Text type="secondary">系统配置、环境变量和API密钥管理</Text>

      <Card style={{ marginTop: 16 }}>
        <Spin spinning={loading}>
          <Form form={form} layout="vertical">
            <Title level={5}><CloudServerOutlined /> 服务配置</Title>
            <Form.Item label="后端服务地址" name="backend_url">
              <Input placeholder="http://localhost:8000" />
            </Form.Item>
            <Form.Item label="启用调试模式" name="debug_mode" valuePropName="checked">
              <Switch />
            </Form.Item>

            <Divider />

            <Title level={5}><KeyOutlined /> API密钥</Title>
            <Form.Item label="Qwen API Key" name="qwen_api_key">
              <Input.Password placeholder="sk-xxx" />
            </Form.Item>
            <Form.Item label="OpenAI API Key" name="openai_api_key">
              <Input.Password placeholder="sk-xxx" />
            </Form.Item>

            <Divider />

            <Space>
              <Button type="primary" onClick={handleSave} loading={saving}>保存设置</Button>
              <Button onClick={() => form.resetFields()}>重置</Button>
              <Button type="link" onClick={loadSettings}>刷新</Button>
            </Space>
          </Form>
        </Spin>
      </Card>
    </div>
  );
}
