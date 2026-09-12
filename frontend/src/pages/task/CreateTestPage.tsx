import { useState, useRef, useEffect } from 'react';
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { useNavigate } from 'react-router-dom';
import { Card, Row, Col, Input, Button, Tabs, Upload, message, Typography, Timeline, Tag, Table, Empty, Segmented, Tooltip, Alert } from 'antd';
import {
  RocketOutlined, UploadOutlined, FileTextOutlined, PictureOutlined, LinkOutlined,
  ThunderboltOutlined, CheckCircleOutlined, LoadingOutlined,
  GlobalOutlined, ApiOutlined, MobileOutlined, DashboardOutlined,
  RobotOutlined, EditOutlined,
} from '@ant-design/icons';
import request from '@/services/request';
import { reuseLifecycleAssets, type LifecycleAsset } from '@/services/assetLifecycle';
import { browserApiUrl } from '@/utils/apiUrl';
import { assertUploadAllowed, formatUploadError } from '@/utils/uploadGuard';
import { getCurrentProjectId, getCurrentProjectName, PROJECT_CHANGED } from '@/pages/product/projectStore';

const { TextArea } = Input;
const { Text } = Typography;

type InputMode = 'text' | 'image' | 'document' | 'url';
type AnalysisStep = {
  title: string;
  status: 'wait' | 'process' | 'finish' | 'error';
  description?: string;
};

// 测试类型定义
type TestType = 'web' | 'api' | 'android' | 'performance';

const TEST_TYPE_OPTIONS: { value: TestType; label: string; icon: React.ReactNode; color: string }[] = [
  { value: 'web', label: 'Web UI', icon: <GlobalOutlined />, color: 'blue' },
  { value: 'api', label: '接口测试', icon: <ApiOutlined />, color: 'green' },
  { value: 'android', label: '移动端', icon: <MobileOutlined />, color: 'orange' },
  { value: 'performance', label: '性能测试', icon: <DashboardOutlined />, color: 'purple' },
];

const TEST_TYPE_TAGS: Record<string, { color: string; label: string }> = {
  web: { color: 'blue', label: 'Web UI' },
  api: { color: 'green', label: 'API' },
  android: { color: 'orange', label: 'Android' },
  performance: { color: 'purple', label: 'Performance' },
};

// 框架映射
const TYPE_FRAMEWORK: Record<string, string> = {
  web: 'Playwright',
  api: 'Pytest',
  android: 'Appium',
  performance: 'JMeter',
};

// ===== 创建任务表单草稿（持久化，切换页面不丢输入） =====
interface DraftState {
  taskName: string;
  requirement: string;
  urlAddress: string;
  imageServerPath: string;
  documentServerPath: string;
  documentFileName: string;
  userTestType: TestType | null;
  inputMode: InputMode;
  setTaskName: (v: string) => void;
  setRequirement: (v: string) => void;
  setUrlAddress: (v: string) => void;
  setImageServerPath: (v: string) => void;
  setDocumentServerPath: (v: string) => void;
  setDocumentFileName: (v: string) => void;
  setUserTestType: (v: TestType | null) => void;
  setInputMode: (v: InputMode) => void;
  clear: () => void;
}

const useCreateTestDraft = create<DraftState>()(
  persist(
    (set) => ({
      taskName: '',
      requirement: '',
      urlAddress: '',
      imageServerPath: '',
      documentServerPath: '',
      documentFileName: '',
      userTestType: null,
      inputMode: 'text',
      setTaskName: (v) => set({ taskName: v }),
      setRequirement: (v) => set({ requirement: v }),
      setUrlAddress: (v) => set({ urlAddress: v }),
      setImageServerPath: (v) => set({ imageServerPath: v }),
      setDocumentServerPath: (v) => set({ documentServerPath: v }),
      setDocumentFileName: (v) => set({ documentFileName: v }),
      setUserTestType: (v) => set({ userTestType: v }),
      setInputMode: (v) => set({ inputMode: v }),
      clear: () => set({
        taskName: '', requirement: '', urlAddress: '', imageServerPath: '',
        documentServerPath: '', documentFileName: '', userTestType: null,
      }),
    }),
    { name: 'create-test-draft' }
  )
);

export default function CreateTestPage() {
  const navigate = useNavigate();
  // 持久化草稿（切换页面不丢输入）
  const {
    taskName, setTaskName,
    inputMode, setInputMode,
    requirement, setRequirement,
    imageServerPath, setImageServerPath,
    documentServerPath, setDocumentServerPath,
    documentFileName, setDocumentFileName,
    urlAddress, setUrlAddress,
    userTestType, setUserTestType,
  } = useCreateTestDraft();
  // 非持久化状态（图片预览/分析过程）
  const [imageUrl, setImageUrl] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisSteps, setAnalysisSteps] = useState<AnalysisStep[]>([]);
  const [taskId, setTaskId] = useState<number | null>(null);
  const [result, setResult] = useState<any>(null);

  // AI 推荐的测试类型
  const [aiTestType, setAiTestType] = useState<TestType | null>(null);
  const [aiConfidence, setAiConfidence] = useState(0);
  const [aiReason, setAiReason] = useState('');
  const [classifying, setClassifying] = useState(false);
  const classifyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [projectName, setProjectName] = useState(getCurrentProjectName());
  const [recentTasks, setRecentTasks] = useState<any[]>([]);
  const [reuseAssets, setReuseAssets] = useState<LifecycleAsset[]>([]);
  const lastProjectId = useRef(getCurrentProjectId());

  useEffect(() => {
    const loadProjectTasks = async () => {
      const projectId = getCurrentProjectId();
      setProjectName(getCurrentProjectName());
      if (lastProjectId.current && lastProjectId.current !== projectId) {
        setAnalysisSteps([]);
        setResult(null);
        setTaskId(null);
      }
      lastProjectId.current = projectId;
      if (!projectId) {
        setRecentTasks([]);
        return;
      }
      try {
        const res: any = await request.get('/requirement/list', {
          params: { page: 1, page_size: 5, project_id: projectId },
        });
        const data = res.data || res;
        setRecentTasks(Array.isArray(data) ? data : (data?.items || []));
      } catch {
        setRecentTasks([]);
      }
    };
    void loadProjectTasks();
    window.addEventListener(PROJECT_CHANGED, loadProjectTasks);
    return () => window.removeEventListener(PROJECT_CHANGED, loadProjectTasks);
  }, []);

  // ── AI 自动判断测试类型（防抖触发）──
  const triggerClassify = (text: string) => {
    if (classifyTimer.current) clearTimeout(classifyTimer.current);
    if (text.trim().length < 4) return;

    classifyTimer.current = setTimeout(async () => {
      setClassifying(true);
      try {
        const res: any = await request.post('/requirement/classify', { requirement: text });
        const data = res.data || res;
        if (data?.test_type) {
          const tType = data.test_type as TestType;
          setAiTestType(tType);
          setAiConfidence(data.confidence || 0);
          setAiReason(data.reason || '');
          setUserTestType(tType); // 用户默认跟随AI推荐
          try {
            const reused = await reuseLifecycleAssets(text.trim());
            setReuseAssets(Array.isArray(reused) ? reused : []);
          } catch {
            setReuseAssets([]);
          }
        } else {
          setAiTestType(null);
          setAiReason('测试类型识别失败');
          message.error('测试类型识别失败');
        }
      } catch (err: any) {
        setAiTestType(null);
        setAiReason(err?.message || '测试类型识别失败');
        message.error(err?.message || '测试类型识别失败');
      } finally {
        setClassifying(false);
      }
    }, 800);
  };

  const handleRequirementChange = (val: string) => {
    setRequirement(val);
    triggerClassify(val);
  };

  const handleUrlChange = (val: string) => {
    setUrlAddress(val);
    if (val.trim().length > 8) triggerClassify(`测试 ${val} 页面功能`);
  };

  // ── 开始智能测试 ──
  const handleStart = async () => {
    if (!taskName.trim()) { message.warning('请输入任务名称'); return; }

    // 确定提交数据
    let reqData: any = {
      requirement: '',
      project_id: getCurrentProjectId() || undefined,
    };

    if (inputMode === 'text') {
      if (!requirement.trim()) { message.warning('请输入测试需求'); return; }
      reqData.requirement = requirement.trim();
    } else if (inputMode === 'image') {
      if (!imageServerPath && !imageUrl) { message.warning('请上传图片'); return; }
      reqData.requirement = `请分析页面截图并生成测试用例`;
      reqData.image_paths = imageServerPath ? [imageServerPath] : [];
    } else if (inputMode === 'document') {
      if (!documentServerPath) { message.warning('请先上传文档到服务器'); return; }
      reqData.requirement = `请分析文档「${documentFileName || documentServerPath}」并生成测试用例`;
      reqData.document_paths = [documentServerPath];
    } else if (inputMode === 'url') {
      if (!urlAddress.trim()) { message.warning('请输入URL地址'); return; }
      reqData.requirement = `测试 ${urlAddress.trim()} 页面功能`;
    }

    // 附加用户选择的测试类型
    if (userTestType) {
      reqData.task_type = userTestType;
    }

    setAnalyzing(true);
    setResult(null);
    setTaskId(null);

    // 初始化分析步骤
    const steps: AnalysisStep[] = [
      { title: '需求解析', status: 'process', description: 'AI 正在理解您的测试需求...' },
      { title: '测试类型识别', status: 'wait' },
      { title: '页面识别', status: 'wait' },
      { title: '用例生成', status: 'wait' },
      { title: '脚本生成', status: 'wait' },
    ];
    setAnalysisSteps([...steps]);

    // 根据 SSE 消息推进步骤状态
    const updateStep = (index: number, status: AnalysisStep['status'], description?: string) => {
      if (index < 0 || index >= steps.length) return;
      steps[index] = { ...steps[index], status, ...(description ? { description } : {}) };
      setAnalysisSteps([...steps]);
    };

    // SSE step_name（英文）→ 步骤索引映射（适配后端 orchestrator 实际消息格式）
    const mapStep = (s: string): number => {
      if (s === 'parse_requirement') return 0;
      if (s === 'classify_type') return 1;
      if (['analyze_image', 'rag_retrieve', 'discover_relations', 'graph_reason'].includes(s)) return 2;
      if (['generate_cases', 'review_cases'].includes(s)) return 3;
      if (s === 'generate_script') return 4;
      return -1;
    };

    try {
      // 1. 提交需求，创建任务
      const res: any = await request.post('/requirement/create', reqData);
      const data = res.data || res;
      if (!(data?.task_id || data?.id)) {
        message.error(data?.message || '提交失败');
        updateStep(0, 'error', '提交失败');
        return;
      }
      const newTaskId = data.task_id || data.id;
      setTaskId(newTaskId);

      // 2. 用 fetch 消费 SSE 流，真实推进进度条
      const response = await fetch(browserApiUrl(`/requirement/analyze/${newTaskId}`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
      });
      if (!response.ok) {
        throw new Error(`分析请求失败 (${response.status})`);
      }
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) throw new Error('无法读取响应流');
      let buffer = '';
      const collectedCases: any[] = [];
      let scriptOutput: any = null;
      let flowState: 'RUNNING' | 'SUCCESS' | 'FAILED' = 'RUNNING';
      let flowError = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (!line.startsWith('data:')) continue;
          try {
            const msg = JSON.parse(line.slice(5).trim());
            const evt: string = msg.event || '';
            const sname: string = msg.step_name || '';
            const idx = mapStep(sname);
            if (evt === 'step_start' && idx >= 0) {
              updateStep(idx, 'process', msg.data?.description || sname);
            } else if (evt === 'step_success' && idx >= 0) {
              const output = msg.data?.output;
              if (sname === 'generate_script' && (output?.status === 'FAILED' || output?.error)) {
                flowState = 'FAILED';
                flowError = output?.error || output?.message || '脚本生成失败';
                updateStep(idx, 'error', flowError);
              } else {
                updateStep(idx, 'finish', msg.data?.description || '完成');
              }
              if (sname === 'generate_cases' && output?.cases) {
                const cs = output.cases;
                if (Array.isArray(cs)) collectedCases.push(...cs);
              }
              if (sname === 'generate_script' && output) {
                scriptOutput = output;
              }
            } else if (evt === 'step_failed' && idx >= 0) {
              flowState = 'FAILED';
              flowError = msg.error || msg.data?.error || '步骤失败';
              updateStep(idx, 'error', flowError);
            } else if (evt === 'step_skipped' && idx >= 0) {
              updateStep(idx, 'finish', '已跳过');
            }
            if (evt === 'flow_failed') {
              flowState = 'FAILED';
              flowError = msg.error || msg.data?.error || '分析失败';
              updateStep(idx >= 0 ? idx : 4, 'error', flowError);
            }
            if (evt === 'flow_success' && flowState !== 'FAILED') {
              flowState = 'SUCCESS';
            }
          } catch { /* 忽略解析错误 */ }
        }
      }

      if (flowState === 'RUNNING') {
        flowState = 'FAILED';
        flowError = flowError || 'SSE 连接中断，分析未完成';
      }

      if (flowState !== 'SUCCESS') {
        steps.forEach((s, i) => {
          if (s.status === 'process' || s.status === 'wait') {
            updateStep(i, 'error', flowError || '未完成');
          }
        });
        setResult(null);
        message.error(flowError || '分析失败');
        return;
      }

      const unfinished = steps.filter((s) => s.status === 'process');
      if (unfinished.length) {
        steps.forEach((s, i) => {
          if (s.status === 'process') updateStep(i, 'error', '步骤未收到完成事件');
        });
        message.error('分析未完整完成');
        return;
      }
      steps.forEach((s, i) => {
        if (s.status === 'wait') updateStep(i, 'finish', '已跳过');
      });
      if (collectedCases.length > 0) updateStep(3, 'finish', `已生成 ${collectedCases.length} 条用例`);
      const framework = userTestType ? TYPE_FRAMEWORK[userTestType] : 'Playwright';
      if (scriptOutput && scriptOutput.status !== 'FAILED') {
        updateStep(4, 'finish', `${framework} 脚本已生成`);
      }

      setResult({ cases: collectedCases, script: scriptOutput });
      message.success('AI 分析完成！');
    } catch (err: any) {
      message.error(err?.message || '请求失败，请重试');
      updateStep(0, 'error', err?.message || '提交失败');
    } finally {
      setAnalyzing(false);
    }
  };

  const inputTabs = [
    {
      key: 'text' as InputMode,
      label: <span><FileTextOutlined /> 文本输入</span>,
      children: (
        <TextArea
          value={requirement}
          onChange={(e) => handleRequirementChange(e.target.value)}
          placeholder="例如：测试商城登录、搜索商品、加入购物车流程"
          autoSize={{ minRows: 6, maxRows: 12 }}
          showCount
          maxLength={2000}
        />
      ),
    },
    {
      key: 'image' as InputMode,
      label: <span><PictureOutlined /> 图片上传</span>,
      children: (
        <Upload.Dragger
          accept="image/*"
          maxCount={1}
          showUploadList={false}
          beforeUpload={(file) => {
            const reader = new FileReader();
            reader.onload = (e) => {
              setImageUrl(e.target?.result as string);
            };
            reader.readAsDataURL(file);
            // 同时上传到服务器获取路径
            const formData = new FormData();
            formData.append('files', file);
            fetch('/api/requirement/upload_images', {
              method: 'POST',
              body: formData,
              credentials: 'include',
            })
              .then(res => res.json())
              .then(data => {
                if (data.data?.image_paths?.[0]) {
                  setImageServerPath(data.data.image_paths[0]);
                  message.success('图片上传成功');
                } else {
                  message.error('图片上传失败');
                }
              })
              .catch(() => message.error('图片上传失败'));
            return false;
          }}
        >
          {imageUrl ? (
            <div>
              <img src={imageUrl} alt="preview" style={{ maxWidth: '100%', maxHeight: 200, marginBottom: 8 }} />
              <p>点击重新选择图片</p>
            </div>
          ) : (
            <>
              <p style={{ fontSize: 40, color: '#999' }}><PictureOutlined /></p>
              <p>点击或拖拽上传页面截图</p>
              <p style={{ color: '#999', fontSize: 12 }}>支持 PNG / JPG / WEBP</p>
            </>
          )}
        </Upload.Dragger>
      ),
    },
    {
      key: 'document' as InputMode,
      label: <span><UploadOutlined /> 文档上传</span>,
      children: (
        <Upload.Dragger
          accept=".pdf,.doc,.docx,.yaml,.yml,.json"
          maxCount={1}
          beforeUpload={(file) => {
            void (async () => {
              try {
                await assertUploadAllowed(file, 'auto');
                const formData = new FormData();
                formData.append('file', file);
                const res = await fetch(browserApiUrl('/requirement/upload_document'), {
                  method: 'POST',
                  body: formData,
                  credentials: 'include',
                });
                const data = await res.json();
                const path = data?.data?.document_path;
                if (!res.ok || !path) {
                  throw new Error(data?.detail || data?.message || '文档上传失败');
                }
                setDocumentServerPath(path);
                setDocumentFileName(data.data.file_name || file.name);
                message.success('文档上传成功');
              } catch (err) {
                setDocumentServerPath('');
                setDocumentFileName('');
                message.error(formatUploadError(err));
              }
            })();
            return false;
          }}
        >
          {documentServerPath ? (
            <p><FileTextOutlined /> {documentFileName || documentServerPath}</p>
          ) : (
            <>
              <p style={{ fontSize: 40, color: '#999' }}><UploadOutlined /></p>
              <p>上传需求文档 / API文档 / Swagger</p>
              <p style={{ color: '#999', fontSize: 12 }}>支持 PDF / Word / TXT / YAML / JSON</p>
            </>
          )}
        </Upload.Dragger>
      ),
    },
    {
      key: 'url' as InputMode,
      label: <span><LinkOutlined /> URL地址</span>,
      children: (
        <Input
          value={urlAddress}
          onChange={(e) => handleUrlChange(e.target.value)}
          placeholder="https://example.com"
          size="large"
        />
      ),
    },
  ];

  return (
    <div>
      {/* 顶部：任务名称 + 开始按钮 */}
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col flex="auto">
            <Input
              value={taskName}
              onChange={(e) => setTaskName(e.target.value)}
              placeholder="输入任务名称，例如：商城核心流程测试"
              size="large"
              prefix={<ThunderboltOutlined style={{ color: '#1677ff' }} />}
            />
          </Col>
          <Col>
            <Button
              type="primary"
              size="large"
              icon={<RocketOutlined />}
              onClick={handleStart}
              loading={analyzing}
              style={{ height: 40, padding: '0 32px', fontWeight: 600 }}
            >
              {analyzing ? 'AI 分析中...' : '开始智能测试'}
            </Button>
          </Col>
        </Row>
        <div style={{ marginTop: 12 }}>
          <Text type="secondary">
            当前项目：<Text strong>{projectName || '未选择'}</Text>
            。点「开始智能测试」后，任务会记到这个项目；换项目会换下面的任务列表。
          </Text>
        </div>
        {reuseAssets.length > 0 && (
          <Alert
            style={{ marginTop: 12 }}
            type="info"
            showIcon
            message="已有可复用测试资产，优先复用而不是重新生成"
            description={
              <div>
                {reuseAssets.slice(0, 5).map((item) => (
                  <div key={item.id}>
                    <Button type="link" onClick={() => navigate(`/asset/lifecycle/${item.stage}`)}>
                      {item.stage_name} · {item.name}
                    </Button>
                  </div>
                ))}
              </div>
            }
          />
        )}
      </Card>

      {/* AI推荐测试类型区域 */}
      {(aiTestType || classifying) && (
        <Card style={{ marginBottom: 16 }} size="small">
          <Row gutter={16} align="middle">
            <Col>
              <RobotOutlined style={{ fontSize: 20, color: '#1677ff' }} />
            </Col>
            <Col flex="auto">
              {classifying ? (
                <Text type="secondary">
                  <LoadingOutlined /> AI 正在判断测试类型...
                </Text>
              ) : (
                <div>
                  <Text strong>AI 推荐测试类型：</Text>{' '}
                  <Tag color={TEST_TYPE_TAGS[aiTestType!]?.color || 'blue'} style={{ fontSize: 14, padding: '2px 12px' }}>
                    {TEST_TYPE_TAGS[aiTestType!]?.label || aiTestType}
                  </Tag>
                  {aiConfidence > 0 && (
                    <Tooltip title={aiReason}>
                      <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                        置信度 {Math.round(aiConfidence * 100)}%
                      </Text>
                    </Tooltip>
                  )}
                </div>
              )}
            </Col>
            <Col>
              <Text type="secondary" style={{ fontSize: 12 }}>
                <EditOutlined /> 您可以调整：
              </Text>
            </Col>
            <Col>
              <Segmented
                value={userTestType || aiTestType || 'web'}
                onChange={(val) => setUserTestType(val as TestType)}
                options={TEST_TYPE_OPTIONS.map((opt) => ({
                  value: opt.value,
                  label: (
                    <span>
                      {opt.icon} {opt.label}
                    </span>
                  ),
                }))}
                size="small"
              />
            </Col>
          </Row>
          {aiReason && !classifying && (
            <Row style={{ marginTop: 8 }}>
              <Col span={24}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  判断依据：{aiReason}
                </Text>
              </Col>
            </Row>
          )}
        </Card>
      )}

      <Row gutter={16}>
        {/* 左侧：输入区域 */}
        <Col span={14}>
          <Card title="输入测试需求" style={{ minHeight: 400 }}>
            <Tabs
              items={inputTabs}
              activeKey={inputMode}
              onChange={(k) => setInputMode(k as InputMode)}
            />
          </Card>
        </Col>

        {/* 右侧：AI 分析过程 */}
        <Col span={10}>
          <Card
            title={<span><ThunderboltOutlined style={{ color: '#1677ff' }} /> AI 实时分析</span>}
            style={{ minHeight: 400 }}
          >
            {analysisSteps.length === 0 ? (
              <Empty
                description="点击「开始智能测试」后，AI 将自动分析"
                image={Empty.PRESENTED_IMAGE_SIMPLE}
              />
            ) : (
              <Timeline
                items={analysisSteps.map((step) => ({
                  color:
                    step.status === 'finish'
                      ? 'green'
                      : step.status === 'error'
                      ? 'red'
                      : step.status === 'process'
                      ? 'blue'
                      : 'gray',
                  dot: step.status === 'process' ? <LoadingOutlined style={{ fontSize: 16 }} /> : undefined,
                  children: (
                    <div>
                      <Text strong>{step.title}</Text>
                      {step.description && (
                        <div>
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {step.description}
                          </Text>
                        </div>
                      )}
                    </div>
                  ),
                }))}
              />
            )}
            {taskId && (
              <div style={{ marginTop: 16, textAlign: 'center' }}>
                <Button type="link" onClick={() => navigate(`/task/${taskId}/detail`)}>
                  查看任务详情 →
                </Button>
              </div>
            )}
          </Card>
        </Col>
      </Row>

      <Card
        title={`本项目任务${projectName ? ` · ${projectName}` : ''}`}
        extra={<Button type="link" onClick={() => navigate('/task')}>查看全部</Button>}
        style={{ marginTop: 16 }}
      >
        {recentTasks.length === 0 ? (
          <Empty description="这个项目还没有测试任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <Table
            dataSource={recentTasks}
            rowKey="id"
            size="small"
            pagination={false}
            columns={[
              {
                title: '任务',
                dataIndex: 'task_name',
                ellipsis: true,
                render: (name: string, row: any) => (
                  <Button type="link" onClick={() => navigate(`/task/${row.id}/detail`)}>
                    {name || row.requirement || `任务 #${row.id}`}
                  </Button>
                ),
              },
              { title: '状态', dataIndex: 'status', width: 100 },
              { title: '类型', dataIndex: 'task_type', width: 80, render: (t: string) => t || '-' },
            ]}
          />
        )}
      </Card>

      {/* 底部：生成结果 */}
      {result && (
        <Card
          title={<span><CheckCircleOutlined style={{ color: '#52c41a' }} /> 生成结果</span>}
          style={{ marginTop: 16 }}
        >
          <Row gutter={16}>
            {result.cases && Array.isArray(result.cases) && result.cases.length > 0 ? (
              <Col span={24}>
                <Table
                  dataSource={result.cases}
                  rowKey={(_, i) => String(i)}
                  size="small"
                  pagination={{ pageSize: 10 }}
                  columns={[
                    { title: '#', width: 50, render: (_, __, i) => i + 1 },
                    { title: '测试场景', dataIndex: 'title', width: 200 },
                    {
                      title: '测试步骤',
                      dataIndex: 'steps',
                      render: (steps: any[]) =>
                        Array.isArray(steps)
                          ? steps.map((s, i) => (
                              <div key={i}>
                                {i + 1}. {s.action || s.description || s.step || JSON.stringify(s)}
                              </div>
                            ))
                          : '-',
                    },
                    {
                      title: '预期结果',
                      dataIndex: 'expected',
                      render: (v: any) => (Array.isArray(v) ? v.join('；') : v || '-'),
                    },
                    {
                      title: '脚本类型',
                      width: 100,
                      render: () => (
                        <Tag color={TEST_TYPE_TAGS[userTestType || 'web']?.color || 'blue'}>
                          {TYPE_FRAMEWORK[userTestType || 'web'] || 'Playwright'}
                        </Tag>
                      ),
                    },
                  ]}
                />
              </Col>
            ) : result.script?.script_content ? (
              <Col span={24}>
                {result.script?.degradation_info && (
                  <Alert
                    type="warning"
                    showIcon
                    message={result.script.degradation_info.message || 'LLM 生成失败，已使用规则模板'}
                    description="当前未配置 AI 模型 API Key，无法生成完整用例与脚本。请在 backend/.env 配置 QWEN_API_KEY 或 DEEPSEEK_API_KEY 后重试。"
                    style={{ marginBottom: 12 }}
                  />
                )}
                <div style={{ marginBottom: 8 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    生成的脚本（{result.script.script_format || 'playwright'}）：
                  </Text>
                </div>
                <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 6, maxHeight: 320, overflow: 'auto', fontSize: 12 }}>
                  {result.script.script_content}
                </pre>
              </Col>
            ) : (
              <Col span={24}>
                <Empty
                  description="未生成用例，请检查 AI 模型 API Key 配置后重试"
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                />
              </Col>
            )}
          </Row>
        </Card>
      )}
    </div>
  );
}
