import { useState, useEffect, useCallback } from 'react';
import { Card, Table, Button, Modal, Form, Input, Space, Popconfirm, message } from 'antd';
import { CloudServerOutlined, PlusOutlined, ReloadOutlined, DeleteOutlined } from '@ant-design/icons';
import { PageHeader } from '../../components/UI';
import request from '../../services/request';

interface EnvItem {
  id: number;
  name: string;
  base_url: string;
  description: string;
  created_at: string;
}

export default function AdminEnvironments() {
  const [list, setList] = useState<EnvItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm();

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const res: any = await request.get('/admin/environments');
      const data = res?.data;
      setList(Array.isArray(data) ? data : data?.items || []);
    } catch {
      message.error('获取环境列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchList();
  }, [fetchList]);

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      const res: any = await request.post('/admin/environments', { ...values, variables: {} });
      if (res?.code === 200) {
        message.success('创建成功');
        setModalOpen(false);
        form.resetFields();
        fetchList();
      } else {
        message.error(res?.message || '创建失败');
      }
    } catch (e: any) {
      if (e?.errorFields) return; // 表单校验未通过
      message.error('创建失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      const res: any = await request.delete(`/admin/environments/${id}`);
      if (res?.code === 200) {
        message.success('删除成功');
        fetchList();
      } else {
        message.error(res?.message || '删除失败');
      }
    } catch {
      message.error('删除失败');
    }
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 70 },
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '页面地址', dataIndex: 'base_url', key: 'base_url', ellipsis: true },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (t: string) => t || '-',
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at' },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_: unknown, r: EnvItem) => (
        <Popconfirm title="确定删除此环境？" onConfirm={() => handleDelete(r.id)} okText="确定" cancelText="取消">
          <Button type="link" size="small" danger icon={<DeleteOutlined />}>
            删除
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <div>
      <PageHeader title="执行环境" subtitle="管理测试时使用的页面地址和环境说明" icon={<CloudServerOutlined />} />
      <Card
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={fetchList}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
              创建环境
            </Button>
          </Space>
        }
      >
        <Table columns={columns} dataSource={list} rowKey="id" loading={loading} pagination={false} />
      </Card>
      <Modal
        title="创建环境"
        open={modalOpen}
        onOk={handleCreate}
        onCancel={() => setModalOpen(false)}
        confirmLoading={submitting}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="请输入环境名称" />
          </Form.Item>
          <Form.Item name="base_url" label="页面地址" rules={[{ required: true, message: '请输入页面地址' }]}>
            <Input placeholder="https://example.com" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} placeholder="环境描述（可选）" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
