/**
 * 用例生成页 - AI驱动测试用例自动生成（任务驱动版）
 *
 * 核心改造：
 *   - 上传 = Task，不是UI行为
 *   - 进度状态由全局 uploadStore 管理
 *   - 页面切换不丢数据
 *   - 刷新页面可恢复（从后端重新加载）
 *
 * 流程：
 *   输入需求 → 创建任务(task_id) → 上传文件 → 启动处理 → SSE监听进度
 */
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Card, Steps, Button, Input, Select, Upload, Space, Typography, Progress,
  Alert, message, Row, Col, Form, Tag, Empty,
} from 'antd';
import {
  UploadOutlined, FileTextOutlined, LinkOutlined, RobotOutlined,
  PictureOutlined, VideoCameraOutlined, CodeOutlined, ApiOutlined,
  ThunderboltOutlined, CloudUploadOutlined,
} from '@ant-design/icons';
import type { UploadFile } from 'antd/es/upload/interface';
import { useUploadStore } from '../../stores/uploadStore';

const { TextArea } = Input;
const { Text, Title } = Typography;

const sourceTypeOptions = [
  { value: 'text', label: '文本输入', icon: <FileTextOutlined /> },
  { value: 'pdf', label: 'PDF文件', icon: <FileTextOutlined /> },
  { value: 'doc', label: 'Word文件', icon: <FileTextOutlined /> },
  { value: 'url', label: 'URL链接', icon: <LinkOutlined /> },
  { value: 'swagger', label: 'Swagger/OpenAPI', icon: <ApiOutlined /> },
  { value: 'image', label: '图片', icon: <PictureOutlined /> },
  { value: 'video', label: '视频', icon: <VideoCameraOutlined /> },
  { value: 'schema', label: '数据Schema', icon: <CodeOutlined /> },
];

const levelMap: Record<string, { color: string; text: string; desc: string }> = {
  l1: { color: 'blue', text: '测试设计', desc: '输出测试意图和测试点' },
  l2: { color: 'orange', text: '用例编译', desc: '输出结构化可执行用例（推荐）' },
  l3: { color: 'red', text: '脚本生成', desc: '输出可执行测试脚本' },
};

export default function CaseGenerate() {
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [sourceType, setSourceType] = useState('text');
  const [compileLevel, setCompileLevel] = useState('l2');
  const [fileList, setFileList] = useState<UploadFile[]>([]);

  // 全局store
  const {
    createTask, uploadFile, startTask, stopListening,
    activeTaskId, tasks,
  } = useUploadStore();

  // 当前活跃任务
  const activeTask = tasks.find(t => t.task_id === activeTaskId);
  const generating = activeTaskId !== null && activeTask?.status !== 'completed' && activeTask?.status !== 'failed' && activeTask?.status !== 'waiting';

  // 清理
  useEffect(() => {
    return () => { stopListening(); };
  }, []);

  const needsFile = ['pdf', 'doc', 'image', 'video', 'schema', 'swagger'].includes(sourceType);
  const hasFile = fileList.length > 0 && fileList[0].originFileObj;

  const handleSourceTypeChange = (val: string) => {
    setSourceType(val);
    if (!['pdf', 'doc', 'image', 'video', 'schema', 'swagger'].includes(val)) {
      setFileList([]);
    }
  };

  const handleGenerate = async () => {
    try {
      const values = await form.validateFields();

      if (needsFile && !hasFile) {
        message.warning('请先上传文件');
        return;
      }

      // Step 1: 创建任务
      const task = await createTask({
        title: values.title || '',
        source_type: sourceType,
        compile_level: compileLevel,
        use_rag: values.use_rag !== false,
        case_types: (values.case_types || ['functional', 'boundary', 'error']),
        max_cases: values.max_cases || 20,
        framework: values.framework || 'pytest',
        base_url: values.base_url || 'http://localhost:8080',
      });

      // Step 2: 上传文件（如果有）
      if (hasFile && fileList[0]?.originFileObj) {
        await uploadFile(task.task_id, fileList[0].originFileObj);
      }

      // Step 3: 启动任务（自动开始SSE监听）
      await startTask(task.task_id, {
        raw_text: values.raw_text || '',
        url: values.url || '',
      });

      message.success(`任务 #${task.task_id} 已创建并启动`);
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        message.error(err.message || '生成失败');
      }
    }
  };

  const handleCancel = () => {
    stopListening();
  };

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 8 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <RobotOutlined /> AI用例生成
          </Title>
          <Text type="secondary">任务驱动 - 页面切换不丢数据，支持断点恢复</Text>
        </Col>
        <Col>
          <Button icon={<CloudUploadOutlined />} onClick={() => navigate('/upload-tasks')}>
            上传任务中心
          </Button>
        </Col>
      </Row>

      <Row gutter={24} style={{ marginTop: 16 }}>
        <Col span={10}>
          <Card title="输入配置" size="small">
            <Form form={form} layout="vertical" initialValues={{
              max_cases: 20, case_types: ['functional', 'error', 'boundary'],
              compile_level: 'l2', framework: 'pytest', base_url: 'http://localhost:8080',
            }}>
              <Form.Item label="编译级别" name="compile_level">
                <Select value={compileLevel} onChange={setCompileLevel} options={[
                  { value: 'l1', label: `${levelMap.l1.text} - ${levelMap.l1.desc}` },
                  { value: 'l2', label: `${levelMap.l2.text} - ${levelMap.l2.desc}` },
                ]} />
              </Form.Item>

              <Form.Item label="任务标题" name="title">
                <Input placeholder="可选，留空自动生成" />
              </Form.Item>

              <Form.Item label="输入类型">
                <Select
                  value={sourceType}
                  onChange={handleSourceTypeChange}
                  style={{ width: '100%' }}
                  options={sourceTypeOptions.map(o => ({ value: o.value, label: <span>{o.icon} {o.label}</span> }))}
                />
              </Form.Item>

              {needsFile && (
                <Form.Item label="上传文件" required>
                  <Upload
                    maxCount={1}
                    fileList={fileList}
                    onChange={({ fileList }) => setFileList(fileList)}
                    beforeUpload={() => false}
                    accept={
                      sourceType === 'pdf' ? '.pdf' :
                      sourceType === 'doc' ? '.doc,.docx' :
                      sourceType === 'image' ? '.png,.jpg,.jpeg,.gif,.bmp' :
                      sourceType === 'video' ? '.mp4,.avi,.mov' :
                      sourceType === 'swagger' ? '.json,.yaml,.yml' :
                      sourceType === 'schema' ? '.json,.xml' :
                      undefined
                    }
                  >
                    <Button icon={<UploadOutlined />}>选择文件</Button>
                  </Upload>
                </Form.Item>
              )}

              {sourceType === 'url' && (
                <Form.Item label="URL地址" name="url" rules={[{ required: true, message: '请输入URL' }]}>
                  <Input placeholder="https://example.com/api-docs" />
                </Form.Item>
              )}

              {(sourceType === 'text' || sourceType === 'schema' || sourceType === 'swagger') && (
                <Form.Item label="内容" name="raw_text" rules={sourceType === 'text' ? [{ required: !hasFile, message: '请输入需求内容' }] : []}>
                  <TextArea rows={6} placeholder={
                    sourceType === 'text' ? '请输入需求描述...' :
                    sourceType === 'swagger' ? '粘贴Swagger/OpenAPI JSON...' :
                    '粘贴Schema定义...'
                  } />
                </Form.Item>
              )}

              <Form.Item label="用例类型" name="case_types">
                <Select mode="multiple" options={[
                  { value: 'functional', label: '功能测试' },
                  { value: 'error', label: '异常测试' },
                  { value: 'boundary', label: '边界测试' },
                ]} />
              </Form.Item>

              <Form.Item label="最大用例数" name="max_cases">
                <Input type="number" min={1} max={100} />
              </Form.Item>

              {compileLevel === 'l3' && (
                <>
                  <Form.Item label="目标框架" name="framework">
                    <Select options={[
                      { value: 'pytest', label: 'Pytest (Python)' },
                      { value: 'unittest', label: 'Unittest (Python)' },
                      { value: 'jest', label: 'Jest (JavaScript)' },
                    ]} />
                  </Form.Item>
                  <Form.Item label="Base URL" name="base_url">
                    <Input placeholder="http://localhost:8080" />
                  </Form.Item>
                </>
              )}

              <Form.Item>
                <Space>
                  <Button type="primary" icon={<ThunderboltOutlined />} onClick={handleGenerate} disabled={generating}>
                    {generating ? '处理中...' : `执行 ${levelMap[compileLevel]?.text}`}
                  </Button>
                  {generating && <Button onClick={handleCancel}>取消监听</Button>}
                </Space>
              </Form.Item>
            </Form>
          </Card>
        </Col>

        <Col span={14}>
          {/* 进度 - 从全局store读取 */}
          {activeTask && generating && (
            <Card title={`任务 #${activeTask.task_id} 进度`} size="small" style={{ marginBottom: 16 }}
              extra={<Tag color={levelMap[activeTask.compile_level]?.color}>{levelMap[activeTask.compile_level]?.text}</Tag>}>
              <Steps current={activeTask.current_step} direction="vertical" size="small" items={[
                { title: '提交任务', description: activeTask.current_step > 0 ? '已提交' : '等待提交' },
                { title: '解析输入', description: activeTask.current_step === 1 ? activeTask.progress_msg : activeTask.current_step > 1 ? '解析完成' : '' },
                { title: '生成用例', description: activeTask.current_step === 2 ? activeTask.progress_msg : activeTask.current_step > 2 ? '生成完成' : '' },
                { title: '标准化', description: activeTask.current_step === 3 ? activeTask.progress_msg : activeTask.current_step > 3 ? '完成' : '' },
                { title: '完成', description: activeTask.current_step >= 4 ? `共生成 ${activeTask.case_count} 条用例` : '' },
              ]} />
              <Progress
                percent={activeTask.progress}
                status={activeTask.status === 'failed' ? 'exception' : 'active'}
                style={{ marginTop: 16 }}
              />
            </Card>
          )}

          {/* 完成结果 - 停留当前页，禁止自动跳转 */}
          {activeTask && activeTask.status === 'completed' && (
            <Card title="编译结果" size="small" extra={
              <Space>
                <Tag color="success">已完成</Tag>
                <Tag color={levelMap[activeTask.compile_level]?.color}>{levelMap[activeTask.compile_level]?.text}</Tag>
              </Space>
            }>
              <Alert type="success" message={`共生成 ${activeTask.case_count} 条草稿用例`} style={{ marginBottom: 12 }} />
              <Space>
                <Button type="primary" icon={<FileTextOutlined />} onClick={() => navigate('/test-design/draft')}>
                  查看结果
                </Button>
                <Button icon={<ThunderboltOutlined />} onClick={handleGenerate}>
                  继续生成
                </Button>
                <Button icon={<CloudUploadOutlined />} onClick={async () => {
                  try {
                    const res = await fetch('/api/assets/v2/publish', {
                      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
                      body: JSON.stringify({ session_id: activeTask.task_id }),
                    });
                    const data = await res.json();
                    if (data.published) {
                      message.success(`已发布 ${data.count || 0} 条`);
                    }
                  } catch { message.error('发布失败'); }
                }}>
                  发布
                </Button>
              </Space>
            </Card>
          )}

          {/* 失败结果 */}
          {activeTask && activeTask.status === 'failed' && (
            <Card title="编译结果" size="small">
              <Alert type="error" message="处理失败" description={activeTask.error_message || '未知错误'} />
            </Card>
          )}

          {/* 空状态 */}
          {!activeTask && (
            <Card title="编译结果" size="small">
              <div style={{ textAlign: 'center', padding: 40 }}>
                <Empty description="提交需求后查看结果" />
              </div>
            </Card>
          )}
        </Col>
      </Row>
    </div>
  );
}
