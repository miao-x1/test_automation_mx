/**
 * 上传任务中心 - 任务驱动型上传架构
 *
 * 核心原则：
 *   - 上传 = Task，不是UI行为
 *   - 所有状态后端托管
 *   - 跨页面可查询
 *   - 页面切换不丢数据
 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Card, Table, Tag, Button, Space, Progress, Typography, message,
  Modal, Upload, Input, Select, Form, Row, Col, Steps,
  Tooltip, Badge,
} from 'antd';
import {
  UploadOutlined, ReloadOutlined,
  CheckCircleOutlined, CloseCircleOutlined, ClockCircleOutlined,
  SyncOutlined, EyeOutlined, FileTextOutlined,
  CloudUploadOutlined, PlusCircleOutlined,
} from '@ant-design/icons';
import type { UploadFile } from 'antd/es/upload/interface';
import { useUploadStore, UploadTaskState } from '../../stores/uploadStore';

const { Text, Title } = Typography;

const statusMap: Record<string, { color: string; label: string; icon: React.ReactNode }> = {
  waiting: { color: 'default', label: '等待中', icon: <ClockCircleOutlined /> },
  parsing: { color: 'processing', label: '解析中', icon: <SyncOutlined spin /> },
  l1_designing: { color: 'processing', label: '设计中', icon: <SyncOutlined spin /> },
  l2_compiling: { color: 'processing', label: '编译中', icon: <SyncOutlined spin /> },
  generating: { color: 'processing', label: '生成中', icon: <SyncOutlined spin /> },
  reviewing: { color: 'warning', label: '评审中', icon: <ClockCircleOutlined /> },
  completed: { color: 'success', label: '已完成', icon: <CheckCircleOutlined /> },
  failed: { color: 'error', label: '失败', icon: <CloseCircleOutlined /> },
};

const sourceTypeOptions = [
  { value: 'pdf', label: 'PDF文件' },
  { value: 'doc', label: 'Word文件' },
  { value: 'image', label: '图片' },
  { value: 'video', label: '视频' },
  { value: 'swagger', label: 'Swagger/OpenAPI' },
  { value: 'schema', label: '数据Schema' },
  { value: 'url', label: 'URL链接' },
  { value: 'text', label: '文本输入' },
];

export default function UploadTaskCenter() {
  const navigate = useNavigate();
  const {
    tasks, loading, activeTaskId,
    fetchTasks, createTask, uploadFile, startTask,
    listenTaskProgress, stopListening, retryTask, fetchTaskStatus,
  } = useUploadStore();

  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [detailTask, setDetailTask] = useState<UploadTaskState | null>(null);
  const [form] = Form.useForm();
  const [fileList, setFileList] = useState<UploadFile[]>([]);

  // 初始化加载
  useEffect(() => {
    fetchTasks();
    // 定时刷新（30秒）
    const timer = setInterval(fetchTasks, 30000);
    return () => {
      clearInterval(timer);
      stopListening();
    };
  }, []);

  // 恢复活跃任务的SSE监听
  useEffect(() => {
    if (activeTaskId) {
      const task = tasks.find(t => t.task_id === activeTaskId);
      if (task && (task.status === 'completed' || task.status === 'failed')) {
        stopListening();
      }
    }
  }, [tasks, activeTaskId]);

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      const needsFile = ['pdf', 'doc', 'image', 'video', 'schema', 'swagger'].includes(values.source_type);

      if (needsFile && fileList.length === 0) {
        message.warning('请先上传文件');
        return;
      }

      // Step 1: 创建任务
      const task = await createTask({
        title: values.title,
        source_type: values.source_type,
        compile_level: values.compile_level || 'l2',
        use_rag: values.use_rag !== false,
        case_types: values.case_types || ['functional', 'boundary', 'error'],
        max_cases: values.max_cases || 20,
        framework: values.framework || 'pytest',
        base_url: values.base_url || 'http://localhost:8080',
      });

      // Step 2: 上传文件（如果有）
      if (needsFile && fileList[0]?.originFileObj) {
        await uploadFile(task.task_id, fileList[0].originFileObj);
      }

      // Step 3: 启动任务
      await startTask(task.task_id, {
        raw_text: values.raw_text || '',
        url: values.url || '',
      });

      message.success(`任务 #${task.task_id} 已创建并启动`);
      setCreateModalOpen(false);
      form.resetFields();
      setFileList([]);
    } catch (err: any) {
      message.error(err.message || '创建任务失败');
    }
  };

  const handleViewProgress = async (task: UploadTaskState) => {
    // 刷新最新状态
    await fetchTaskStatus(task.task_id);
    setDetailTask(task);

    // 如果任务在运行中，开始监听SSE
    if (!['completed', 'failed', 'waiting'].includes(task.status)) {
      listenTaskProgress(task.task_id);
    }
  };

  const handleRetry = async (task: UploadTaskState) => {
    try {
      await retryTask(task.task_id);
      message.success('任务已重置');
      fetchTasks();
    } catch (err: any) {
      message.error(err.message || '重试失败');
    }
  };

  // 获取最新详情
  const currentDetail = detailTask
    ? tasks.find(t => t.task_id === detailTask.task_id) || detailTask
    : null;

  const columns = [
    {
      title: 'ID',
      dataIndex: 'task_id',
      key: 'task_id',
      width: 60,
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
    },
    {
      title: '类型',
      dataIndex: 'source_type',
      key: 'source_type',
      width: 100,
      render: (v: string) => <Tag>{sourceTypeOptions.find(o => o.value === v)?.label || v}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (v: string) => {
        const s = statusMap[v] || { color: 'default', label: v, icon: null };
        return <Tag color={s.color} icon={s.icon}>{s.label}</Tag>;
      },
    },
    {
      title: '进度',
      key: 'progress',
      width: 200,
      render: (_: any, record: UploadTaskState) => {
        if (record.status === 'completed') return <Progress percent={100} size="small" />;
        if (record.status === 'failed') return <Progress percent={record.progress} status="exception" size="small" />;
        if (record.progress > 0) return <Progress percent={record.progress} size="small" />;
        return <Text type="secondary">-</Text>;
      },
    },
    {
      title: '用例数',
      dataIndex: 'case_count',
      key: 'case_count',
      width: 80,
      render: (v: number) => v > 0 ? <Badge count={v} style={{ backgroundColor: '#1890ff' }} /> : <Text type="secondary">0</Text>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (v: string) => v ? new Date(v).toLocaleString() : '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      render: (_: any, record: UploadTaskState) => (
        <Space>
          <Tooltip title="查看进度">
            <Button size="small" icon={<EyeOutlined />} onClick={() => handleViewProgress(record)} />
          </Tooltip>
          {record.status === 'failed' && (
            <Tooltip title="重试">
              <Button size="small" icon={<ReloadOutlined />} onClick={() => handleRetry(record)} />
            </Tooltip>
          )}
          {record.status === 'completed' && record.case_count > 0 && (
            <Tooltip title="查看资产">
              <Button size="small" type="primary" icon={<FileTextOutlined />}
                onClick={() => navigate('/test-assets')} />
            </Tooltip>
          )}
        </Space>
      ),
    },
  ];

  const needsFile = ['pdf', 'doc', 'image', 'video', 'schema', 'swagger'].includes(
    Form.useWatch('source_type', form) || 'text'
  );

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <CloudUploadOutlined /> 上传任务中心
          </Title>
          <Text type="secondary">任务驱动型上传系统 - 页面切换不丢数据，支持断点恢复</Text>
        </Col>
        <Col>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={fetchTasks} loading={loading}>刷新</Button>
            <Button type="primary" icon={<PlusCircleOutlined />} onClick={() => setCreateModalOpen(true)}>
              新建上传任务
            </Button>
          </Space>
        </Col>
      </Row>

      {/* 运行中任务快速预览 */}
      {tasks.filter(t => !['completed', 'failed', 'waiting'].includes(t.status)).length > 0 && (
        <Card size="small" title="运行中的任务" style={{ marginBottom: 16 }}>
          <Row gutter={16}>
            {tasks.filter(t => !['completed', 'failed', 'waiting'].includes(t.status)).map(task => (
              <Col span={8} key={task.task_id}>
                <Card size="small" style={{ borderLeft: '3px solid #1890ff' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Text strong>#{task.task_id} {task.title}</Text>
                    <Tag color={statusMap[task.status]?.color} icon={statusMap[task.status]?.icon}>
                      {statusMap[task.status]?.label}
                    </Tag>
                  </div>
                  <Progress percent={task.progress} size="small" style={{ marginTop: 8 }} />
                  <Text type="secondary" style={{ fontSize: 12 }}>{task.progress_msg}</Text>
                </Card>
              </Col>
            ))}
          </Row>
        </Card>
      )}

      {/* 任务列表 */}
      <Card size="small">
        <Table
          dataSource={tasks}
          columns={columns}
          rowKey="task_id"
          loading={loading}
          pagination={{ pageSize: 15, showTotal: t => `共 ${t} 个任务` }}
          size="small"
        />
      </Card>

      {/* 创建任务弹窗 */}
      <Modal
        title="新建上传任务"
        open={createModalOpen}
        onOk={handleCreate}
        onCancel={() => { setCreateModalOpen(false); form.resetFields(); setFileList([]); }}
        width={600}
        okText="创建并启动"
      >
        <Form form={form} layout="vertical" initialValues={{
          source_type: 'pdf', compile_level: 'l2',
          max_cases: 20, case_types: ['functional', 'error', 'boundary'],
          framework: 'pytest', base_url: 'http://localhost:8080',
        }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="任务标题" name="title">
                <Input placeholder="可选，留空自动生成" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="输入类型" name="source_type">
                <Select options={sourceTypeOptions} />
              </Form.Item>
            </Col>
          </Row>

          {needsFile && (
            <Form.Item label="上传文件" required>
              <Upload
                maxCount={1}
                fileList={fileList}
                onChange={({ fileList }) => setFileList(fileList)}
                beforeUpload={() => false}
              >
                <Button icon={<UploadOutlined />}>选择文件</Button>
              </Upload>
            </Form.Item>
          )}

          <Form.Item noStyle shouldUpdate>
            {({ getFieldValue }) =>
              getFieldValue('source_type') === 'url' ? (
                <Form.Item label="URL地址" name="url" rules={[{ required: true, message: '请输入URL' }]}>
                  <Input placeholder="https://example.com/api-docs" />
                </Form.Item>
              ) : getFieldValue('source_type') === 'text' ? (
                <Form.Item label="需求内容" name="raw_text" rules={[{ required: true, message: '请输入需求内容' }]}>
                  <Input.TextArea rows={4} placeholder="请输入需求描述..." />
                </Form.Item>
              ) : null
            }
          </Form.Item>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="编译级别" name="compile_level">
                <Select options={[
                  { value: 'l1', label: '测试设计' },
                  { value: 'l2', label: '用例编译（推荐）' },
                ]} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="最大用例数" name="max_cases">
                <Input type="number" min={1} max={100} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      {/* 任务详情弹窗 */}
      <Modal
        title={currentDetail ? `任务 #${currentDetail.task_id} 详情` : '任务详情'}
        open={!!currentDetail}
        onCancel={() => { setDetailTask(null); stopListening(); }}
        footer={null}
        width={600}
      >
        {currentDetail && (
          <div>
            <Steps current={currentDetail.current_step} direction="vertical" size="small" items={[
              { title: '提交任务', description: currentDetail.current_step > 0 ? '已提交' : '等待提交' },
              { title: '解析输入', description: currentDetail.current_step === 1 ? currentDetail.progress_msg : currentDetail.current_step > 1 ? '解析完成' : '' },
              { title: '生成用例', description: currentDetail.current_step === 2 ? currentDetail.progress_msg : currentDetail.current_step > 2 ? '生成完成' : '' },
              { title: '标准化', description: currentDetail.current_step === 3 ? currentDetail.progress_msg : currentDetail.current_step > 3 ? '完成' : '' },
              { title: '完成', description: currentDetail.current_step >= 4 ? `共生成 ${currentDetail.case_count} 条用例` : '' },
            ]} />
            <Progress
              percent={currentDetail.progress}
              status={currentDetail.status === 'failed' ? 'exception' : currentDetail.status === 'completed' ? 'success' : 'active'}
              style={{ marginTop: 16 }}
            />
            {currentDetail.error_message && (
              <div style={{ marginTop: 12 }}>
                <Text type="danger">错误: {currentDetail.error_message}</Text>
              </div>
            )}
            {currentDetail.status === 'completed' && currentDetail.case_count > 0 && (
              <div style={{ marginTop: 12, textAlign: 'center' }}>
                <Button type="primary" icon={<FileTextOutlined />} onClick={() => { setDetailTask(null); navigate('/test-assets'); }}>
                  查看测试资产
                </Button>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
