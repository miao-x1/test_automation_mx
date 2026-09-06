/**
 * 任务详情 — 控制塔页面
 *
 * 三栏布局：
 *   左栏（任务信息）：状态、类型、URL、截图、配置
 *   中栏（执行流）：SSE时间线 + 元素/脚本/记录/结果 Tab
 *   右栏（操作面板）：执行/重跑/下载/分析按钮
 *
 * 唯一执行入口，所有测试类型统一
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import {
  Card, Button, Tag, Space, Table, Tabs, Statistic, Row, Col, Popconfirm,
  message, Spin, Alert, Typography, Progress, Image as AntImage, Modal,
  Descriptions, Divider, Collapse, Timeline,
} from 'antd';
import {
  PlayCircleOutlined, ReloadOutlined, DownloadOutlined, DeleteOutlined,
  EyeOutlined, CodeOutlined, MergeCellsOutlined,
  CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined,
  ThunderboltOutlined, FileTextOutlined, CameraOutlined,
  EditOutlined, AppstoreOutlined,
  BugOutlined, GlobalOutlined, PictureOutlined,
  InfoCircleOutlined,
  RobotOutlined, BulbOutlined, WarningOutlined, ExperimentOutlined,
} from '@ant-design/icons';
import {
  getTask, deleteTask, rerunTask, downloadScript,
  executeScript, getTaskExecutions, getReportUrl, getScreenshotUrl,
  updateScript, UIElement, ExecutionRecord,
} from '../services/task';
import request from '../services/request';
import { getPageElements, PageElement } from '../services/page';
import { TASK_TYPE_LABELS, TASK_TYPE_COLORS, listProviders, ProviderInfo as ProviderInfoType } from '../services/asset';
import { TYPE_LABELS as AI_TYPE_LABELS, TYPE_COLORS as AI_TYPE_COLORS, TYPE_ICONS as AI_TYPE_ICONS } from '../services/taskTypeDetector';
import { StatusTag, PageHeader } from '../components/UI';
import { TaskUnderstanding } from '../components/TaskUnderstanding';
import { ExecutionTimeline, buildTimelineFromExecution } from '../components/ExecutionTimeline';
import { SmartSuggestion } from '../components/SmartSuggestion';

const { Text } = Typography;

const SOURCE_CONFIG: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  vision: { label: 'Vision', color: 'purple', icon: <EyeOutlined /> },
  dom: { label: 'DOM', color: 'green', icon: <CodeOutlined /> },
  merge: { label: '融合', color: 'blue', icon: <MergeCellsOutlined /> },
};

const TaskDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const autoStarted = useRef(false);
  const [task, setTask] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [sseMessages, setSseMessages] = useState<string[]>([]);
  const [sseProgress, setSseProgress] = useState(0);
  const [elementFilter, setElementFilter] = useState<string>('all');

  // 执行相关
  const [executing, setExecuting] = useState(false);
  const [execSseMessages, setExecSseMessages] = useState<string[]>([]);
  const [execSseProgress, setExecSseProgress] = useState(0);
  const [executionRecords, setExecutionRecords] = useState<ExecutionRecord[]>([]);
  const [logModalVisible, setLogModalVisible] = useState(false);
  const [logContent, setLogContent] = useState('');
  const [screenshotModalVisible, setScreenshotModalVisible] = useState(false);
  const [screenshotUrl, setScreenshotUrl] = useState('');

  // 脚本编辑
  const [scriptEditing, setScriptEditing] = useState(false);
  const [scriptContent, setScriptContent] = useState('');
  const [scriptSaving, setScriptSaving] = useState(false);

  // 测试类型
  const [taskType, setTaskType] = useState<string>(task?.task_type || 'web');
  const [_providers, setProviders] = useState<ProviderInfoType[]>([]);

  // 结果
  const [pageElements, setPageElements] = useState<PageElement[]>([]);
  const [activeTab, setActiveTab] = useState('elements');
  const [pageError, setPageError] = useState<string | null>(null);

  // AI增强功能
  const [understanding, setUnderstanding] = useState<any>(null);
  const [understandingLoading, setUnderstandingLoading] = useState(false);
  const [timeline, setTimeline] = useState<any[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [failureAnalysis, setFailureAnalysis] = useState<any>(null);
  const [optimizing, setOptimizing] = useState(false);

  const fetchTask = useCallback(async () => {
    if (!id) return;
    try {
      const res = await getTask(Number(id));
      setTask((res as any)?.data || res);
      setPageError(null);
    } catch (e: any) {
      console.error('[TaskDetail] fetchTask failed:', e);
      setTask(null);
      setPageError(e?.message || '加载任务失败');
    } finally {
      setLoading(false);
    }
  }, [id]);

  const fetchExecutions = useCallback(async () => {
    if (!id) return;
    try {
      const res = await getTaskExecutions(Number(id));
      const data = (res as any)?.data || res;
      setExecutionRecords(Array.isArray(data) ? data : []);
    } catch (e: any) {
      console.error('[TaskDetail] fetchExecutions failed:', e);
      setExecutionRecords([]);
    }
  }, [id]);

  const fetchPageElements = useCallback(async () => {
    if (!id) return;
    try {
      const res = await getPageElements(Number(id));
      const data = (res as any)?.data || res;
      setPageElements(Array.isArray(data) ? data : []);
    } catch (e: any) {
      console.error('[TaskDetail] fetchPageElements failed:', e);
      setPageElements([]);
    }
  }, [id]);

  // AI任务理解
  const fetchUnderstanding = useCallback(async () => {
    if (!id) return;
    setUnderstandingLoading(true);
    try {
      const res: any = await request.get(`/tasks/${id}/understanding`);
      const data = res?.data || res;
      if (data && (data.goal || data.summary)) {
        setUnderstanding(data);
      }
    } catch {
      /* silent fallback - 不显示AI理解卡片 */
    } finally {
      setUnderstandingLoading(false);
    }
  }, [id]);

  // AI执行时间线
  const fetchTimeline = useCallback(async () => {
    if (!id) return;
    setTimelineLoading(true);
    try {
      const res: any = await request.get(`/orchestrator/timeline/${id}`);
      const data = res?.data || res;
      if (Array.isArray(data)) {
        setTimeline(data);
      } else if (data?.steps && Array.isArray(data.steps)) {
        setTimeline(data.steps);
      }
    } catch {
      /* silent fallback */
    } finally {
      setTimelineLoading(false);
    }
  }, [id]);

  // AI失败分析
  const fetchFailureAnalysis = useCallback(async (executionId: number) => {
    if (!executionId) return;
    try {
      const res: any = await request.post(`/executions/${executionId}/analyze`);
      const data = res?.data || res;
      if (data && (data.error_cause || data.fix_suggestion)) {
        setFailureAnalysis(data);
      }
    } catch {
      /* silent fallback */
    }
  }, []);

  useEffect(() => { fetchTask(); fetchExecutions(); fetchPageElements(); loadProviders(); fetchUnderstanding(); fetchTimeline(); }, [fetchTask, fetchExecutions, fetchPageElements, fetchUnderstanding, fetchTimeline]);

  const loadProviders = async () => {
    try {
      setProviders(await listProviders());
    } catch (e: any) {
      console.error('[TaskDetail] loadProviders failed:', e);
    }
  };

  useEffect(() => {
    if (task?.task_type) setTaskType(task.task_type);
  }, [task]);

  useEffect(() => {
    if (!autoStarted.current && task && task.status === 'pending' && location.state?.autoStart) {
      autoStarted.current = true;
      startAnalysis();
    }
  }, [task]);

  // 执行失败时自动触发AI失败分析
  useEffect(() => {
    const failed = executionRecords.find(r => r.status === 'failed');
    if (failed) {
      fetchFailureAnalysis(failed.id);
    } else {
      setFailureAnalysis(null);
    }
  }, [executionRecords, fetchFailureAnalysis]);

  const startAnalysis = () => {
    if (!id) return;
    setAnalyzing(true); setSseMessages([]); setSseProgress(0);
    const es = new EventSource(`/api/tasks/${id}/analyze`);
    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setSseMessages(prev => [...prev, data.message || data.step || '']);
        if (data.progress) setSseProgress(prev => Math.max(prev, data.progress));
        if (data.warning) Modal.warning({ title: '未识别到页面URL', content: data.warning });
        if (data.step === '任务完成' || data.error) { es.close(); setAnalyzing(false); fetchTask(); if (data.step === '任务完成') message.success('分析完成'); }
      } catch { /* ignore */ }
    };
    es.onerror = () => { es.close(); setAnalyzing(false); fetchTask(); };
  };

  const handleExecute = async () => {
    if (!id) return;
    try {
      const res = await executeScript(Number(id));
      const data = (res as any)?.data || res;
      const executionId = data.execution_id;
      if (!executionId) { message.error('创建执行任务失败'); return; }
      setExecuting(true); setExecSseMessages([]); setExecSseProgress(0); setActiveTab('execution');
      const es = new EventSource(`/api/executions/${executionId}/stream`);
      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setExecSseMessages(prev => [...prev, data.message || data.step || '']);
          if (data.progress) setExecSseProgress(prev => Math.max(prev, data.progress));
          if (data.step === '执行完成' || data.step === '执行异常') {
            es.close(); setExecuting(false); fetchExecutions(); fetchTask(); fetchPageElements();
            if (data.step === '执行完成') { message.success('执行完成'); setActiveTab('result'); }
            else { message.error('执行失败'); }
          }
        } catch { /* ignore */ }
      };
      es.onerror = () => { es.close(); setExecuting(false); fetchExecutions(); fetchTask(); };
    } catch (e: any) { message.error(e?.response?.data?.detail || '执行失败'); }
  };

  const handleViewLog = (record: ExecutionRecord) => { setLogContent(record.log_content || '暂无日志'); setLogModalVisible(true); };
  const handleViewScreenshot = (record: ExecutionRecord) => { setScreenshotUrl(getScreenshotUrl(record.id)); setScreenshotModalVisible(true); };
  const handleViewReport = (record: ExecutionRecord) => { window.open(getReportUrl(record.id), '_blank'); };

  const handleEditScript = () => { if (task?.script?.script_content) { setScriptContent(task.script.script_content); setScriptEditing(true); } };
  const handleSaveScript = async () => {
    if (!id) return;
    setScriptSaving(true);
    try { await updateScript(Number(id), scriptContent); message.success('脚本保存成功'); setScriptEditing(false); fetchTask(); }
    catch { message.error('脚本保存失败'); }
    finally { setScriptSaving(false); }
  };

  const handleDelete = async () => { if (!id) return; await deleteTask(Number(id)); message.success('删除成功'); navigate('/manage'); };
  const handleRerun = async () => { if (!id) return; await rerunTask(Number(id)); startAnalysis(); };

  // 一键优化脚本
  const handleOptimizeScript = async () => {
    if (!id) return;
    setOptimizing(true);
    try {
      await request.post(`/tasks/${id}/optimize-script`, { optimization_type: 'general' });
      message.success('脚本优化完成');
      fetchTask(); // 重新加载任务数据以显示更新后的脚本
    } catch {
      message.error('脚本优化失败');
    } finally {
      setOptimizing(false);
    }
  };

  // 一键自动修复（失败分析后）
  const handleAutoFix = async (executionId: number) => {
    if (!id || !executionId) return;
    try {
      const res: any = await request.post(`/tasks/${id}/auto_fix`, { execution_id: executionId });
      if (res?.code === 200 || res?.data) {
        message.success('自动修复完成，脚本已更新');
        fetchTask();
        fetchExecutions();
      } else {
        message.error(res?.message || '自动修复失败');
      }
    } catch {
      message.error('自动修复请求失败');
    }
  };

  if (loading) return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>;
  if (pageError && !task) return (
    <Card>
      <Alert type="error" message="加载任务失败" description={pageError} showIcon />
      <Button style={{ marginTop: 12 }} onClick={() => { setLoading(true); fetchTask(); }}>重试</Button>
    </Card>
  );
  if (!task) return <Card><Alert type="warning" message="任务不存在" showIcon /></Card>;

  const uiElements: UIElement[] = task.ui_elements || [];
  const filteredElements = elementFilter === 'all' ? uiElements : uiElements.filter(e => e.source === elementFilter);
  const visionCount = uiElements.filter(e => e.source === 'vision').length;
  const domCount = uiElements.filter(e => e.source === 'dom').length;
  const mergeCount = uiElements.filter(e => e.source === 'merge').length;
  const hasExecutionResult = executionRecords.length > 0 && executionRecords.some(r => r.status === 'success' || r.status === 'failed');
  const latestSuccessExec = executionRecords.find(r => r.status === 'success');
  const latestFailedExec = executionRecords.find(r => r.status === 'failed');

  // ==================== 三栏布局 ====================
  return (
    <div>
      {/* === 顶部 Header === */}
      <PageHeader
        title={task.task_name}
        status={task.status}
        icon={task.input_mode === 'image' ? <PictureOutlined /> : <GlobalOutlined />}
        subtitle={task.page_url || `任务 #${task.id}`}
        backTo="/manage"
        actions={
          <Space size="small">
            {/* 二级操作：重新执行 */}
            {task.script && !executing && !analyzing && task.status !== 'pending' && (
              <Button icon={<ReloadOutlined />} onClick={handleRerun} size="large">
                重新执行
              </Button>
            )}
            {/* 主操作：最多1个 Primary */}
            {task.script && !executing && !analyzing && (
              <Button type="primary" icon={<ThunderboltOutlined />} onClick={handleExecute} size="large">
                开始执行
              </Button>
            )}
            {executing && <Button icon={<LoadingOutlined />} disabled size="large">执行中...</Button>}
          </Space>
        }
      />

      {/* === AI任务理解层（API驱动，渐变蓝卡片） === */}
      {understandingLoading ? (
        <Card size="small" style={{ marginBottom: 16, textAlign: 'center', minHeight: 80, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Spin tip="AI正在理解任务...">
            <div style={{ minHeight: 40 }} />
          </Spin>
        </Card>
      ) : understanding ? (
        <Card
          size="small"
          style={{ marginBottom: 16, background: '#ffffff' }}
          styles={{ body: { padding: '16px 20px' } }}
        >
          <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
            <RobotOutlined style={{ fontSize: 18, marginRight: 8 }} />
            <span style={{ fontSize: 16, fontWeight: 500, color: '#1c1c1c' }}>AI 任务理解</span>
            {understanding.confidence != null && (
              <Tag style={{ marginLeft: 'auto' }}>
                置信度: {(understanding.confidence * 100).toFixed(0)}%
              </Tag>
            )}
          </div>

          <Descriptions column={1} size="small" labelStyle={{ color: '#6b6560', width: 90 }} contentStyle={{ color: '#1c1c1c' }}>
            {understanding.goal && (
              <Descriptions.Item label="你的目标">{understanding.goal}</Descriptions.Item>
            )}
            {understanding.test_object && (
              <Descriptions.Item label="测试对象">{understanding.test_object}</Descriptions.Item>
            )}
            {understanding.test_flow && (
              <Descriptions.Item label="测试流程">{understanding.test_flow}</Descriptions.Item>
            )}
          </Descriptions>

          {understanding.risk_points && understanding.risk_points.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div style={{ color: '#1c1c1c', fontWeight: 500, marginBottom: 6 }}>
                <WarningOutlined style={{ marginRight: 4 }} />风险点：
              </div>
              <Space size={[8, 4]} wrap>
                {understanding.risk_points.map((risk: string, i: number) => (
                  <Tag key={i}>{risk}</Tag>
                ))}
              </Space>
            </div>
          )}

          {understanding.coverage && (
            <div style={{ marginTop: 12, color: '#6b6560' }}>
              <BulbOutlined style={{ marginRight: 4 }} />
              预计覆盖范围：{understanding.coverage}
            </div>
          )}
        </Card>
      ) : (
        /* API未返回时使用本地理解组件作为兜底 */
        <TaskUnderstanding
          taskId={Number(id)}
          requirement={task.requirement || task.task_name}
          pageUrl={task.page_url || undefined}
        />
      )}

      {/* === 三栏主体 === */}
      <Row gutter={16}>
        {/* ===== 左栏：任务信息 ===== */}
        <Col xs={24} lg={6}>
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            {/* 状态卡片 */}
            <Card size="small" title={<Space><InfoCircleOutlined /> 任务状态</Space>}>
              <div style={{ textAlign: 'center', padding: '12px 0' }}>
                <StatusTag status={task.status} />
                {task.status === 'processing' && <Progress percent={sseProgress} size="small" style={{ marginTop: 8 }} />}
              </div>
              <Descriptions size="small" column={1}>
                <Descriptions.Item label="ID">{task.id}</Descriptions.Item>
                <Descriptions.Item label="输入模式">
                  <Tag color={task.input_mode === 'image' ? 'purple' : 'green'}>
                    {task.input_mode === 'image' ? '图片' : 'URL'}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="测试类型">
                  <Tag color={AI_TYPE_COLORS[taskType] || TASK_TYPE_COLORS[taskType]}>
                    {AI_TYPE_ICONS[taskType] || ''} {AI_TYPE_LABELS[taskType] || TASK_TYPE_LABELS[taskType]}
                  </Tag>
                  <Text type="secondary" style={{ fontSize: 10, marginLeft: 4 }}>AI自动识别</Text>
                </Descriptions.Item>
                <Descriptions.Item label="创建时间">{task.created_at}</Descriptions.Item>
              </Descriptions>
            </Card>

            {/* 截图 */}
            {task.input_mode === 'image' && task.images?.length > 0 && (
              <Card size="small" title="上传截图">
                {task.images.map((img: any) => (
                  <AntImage key={img.id} src={`/api/tasks/images/${img.id}`} style={{ maxWidth: '100%', maxHeight: 160, objectFit: 'contain' }} />
                ))}
              </Card>
            )}

            {/* 元素统计 */}
            {uiElements.length > 0 && (
              <Card size="small" title="元素统计">
                <Row gutter={8}>
                  <Col span={8}><Statistic title="Vision" value={visionCount} valueStyle={{ color: '#722ed1', fontSize: 18 }} /></Col>
                  <Col span={8}><Statistic title="DOM" value={domCount} valueStyle={{ color: '#52c41a', fontSize: 18 }} /></Col>
                  <Col span={8}><Statistic title="融合" value={mergeCount} valueStyle={{ color: '#1677ff', fontSize: 18 }} /></Col>
                </Row>
              </Card>
            )}

            {/* 执行概要 */}
            {executionRecords.length > 0 && (
              <Card size="small" title="执行概要">
                <Descriptions size="small" column={1}>
                  <Descriptions.Item label="执行次数">{executionRecords.length}</Descriptions.Item>
                  <Descriptions.Item label="最近成功">{latestSuccessExec ? `#${latestSuccessExec.id}` : '-'}</Descriptions.Item>
                  <Descriptions.Item label="最近失败">{latestFailedExec ? `#${latestFailedExec.id}` : '-'}</Descriptions.Item>
                </Descriptions>
              </Card>
            )}
          </Space>
        </Col>

        {/* ===== 中栏：执行流 ===== */}
        <Col xs={24} lg={12}>
          {/* SSE进度 */}
          {(analyzing || executing) && (
            <Card size="small" style={{ marginBottom: 16 }}>
              <Progress percent={analyzing ? sseProgress : execSseProgress} status="active" />
              <div style={{ maxHeight: 100, overflow: 'auto', marginTop: 8, background: '#1e1e1e', padding: 8, borderRadius: 4 }}>
                {(analyzing ? sseMessages : execSseMessages).map((msg, i) => (
                  <div key={i} style={{ fontSize: 12, color: '#d4d4d4', fontFamily: 'Consolas, monospace' }}>{msg}</div>
                ))}
              </div>
            </Card>
          )}

          {/* 失败提示 */}
          {task.status === 'failed' && task.error_message && (
            <Alert type="error" message={task.error_message} showIcon style={{ marginBottom: 16 }} />
          )}

          {/* 内容Tab */}
          <Card size="small">
            <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
              {
                key: 'elements',
                label: `元素库 (${uiElements.length})`,
                children: (
                  <>
                    <Space style={{ marginBottom: 12 }}>
                      {['all', 'vision', 'dom', 'merge'].map(f => (
                        <Button key={f} size="small" type={elementFilter === f ? 'primary' : 'default'}
                          onClick={() => setElementFilter(f)} icon={f !== 'all' ? SOURCE_CONFIG[f]?.icon : undefined}>
                          {f === 'all' ? '全部' : SOURCE_CONFIG[f]?.label}
                          {f === 'vision' && ` (${visionCount})`}
                          {f === 'dom' && ` (${domCount})`}
                          {f === 'merge' && ` (${mergeCount})`}
                        </Button>
                      ))}
                    </Space>
                    <Table columns={[
                      { title: '来源', dataIndex: 'source', width: 80, render: (s: string) => { const c = SOURCE_CONFIG[s] || SOURCE_CONFIG.vision; return <Tag color={c.color} icon={c.icon}>{c.label}</Tag>; } },
                      { title: '名称', dataIndex: 'name', width: 120 },
                      { title: '类型', dataIndex: 'type', width: 80, render: (t: string) => <Tag>{t}</Tag> },
                      { title: '定位器', dataIndex: 'locator', ellipsis: true, render: (l: string) => l ? <Text code>{l}</Text> : '-' },
                      { title: '置信度', dataIndex: 'confidence', width: 80, render: (c: number) => c ? <Text type={c >= 0.8 ? 'success' : 'warning'}>{(c * 100).toFixed(0)}%</Text> : '-' },
                    ]} dataSource={filteredElements} rowKey="id" size="small" pagination={{ pageSize: 15 }} scroll={{ x: 800 }} />
                  </>
                ),
              },
              ...(task.script ? [{
                key: 'script',
                label: '脚本',
                children: (
                  <div>
                    <Space style={{ marginBottom: 8 }}>
                      {!scriptEditing ? (
                        <>
                          <Button icon={<EditOutlined />} onClick={handleEditScript}>编辑</Button>
                          <Button
                            type="primary"
                            ghost
                            icon={<ExperimentOutlined />}
                            loading={optimizing}
                            onClick={handleOptimizeScript}
                          >
                            一键优化脚本
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button type="primary" loading={scriptSaving} onClick={handleSaveScript}>保存</Button>
                          <Button onClick={() => setScriptEditing(false)}>取消</Button>
                        </>
                      )}
                    </Space>
                    {scriptEditing ? (
                      <textarea value={scriptContent} onChange={e => setScriptContent(e.target.value)}
                        style={{ width: '100%', minHeight: 400, background: '#1e1e1e', color: '#d4d4d4', padding: 12, borderRadius: 6, fontSize: 13, fontFamily: 'Consolas, monospace', border: '1px solid #444', resize: 'vertical', lineHeight: 1.6 }} spellCheck={false} />
                    ) : (
                      <pre style={{ background: '#1e1e1e', color: '#d4d4d4', padding: 12, borderRadius: 6, overflow: 'auto', fontSize: 13, fontFamily: 'Consolas, monospace', lineHeight: 1.6, maxHeight: 500 }}>
                        {task.script.script_content}
                      </pre>
                    )}
                  </div>
                ),
              }] : []),
              ...(task.script ? [{
                key: 'execution',
                label: `执行 (${executionRecords.length})`,
                children: (
                  <div>
                    {/* AI失败分析 */}
                    {failureAnalysis && (
                      <Card
                        size="small"
                        style={{ marginBottom: 16, borderColor: '#ff4d4f', background: '#fff2f0' }}
                        title={<Space><BugOutlined style={{ color: '#ff4d4f' }} /> AI 失败分析</Space>}
                      >
                        <Descriptions column={1} size="small">
                          <Descriptions.Item label="错误原因">{failureAnalysis.error_cause}</Descriptions.Item>
                          <Descriptions.Item label="影响范围">{failureAnalysis.impact_scope}</Descriptions.Item>
                          <Descriptions.Item label="修复方案">{failureAnalysis.fix_suggestion}</Descriptions.Item>
                        </Descriptions>
                        <Space style={{ marginTop: 12 }}>
                          {failureAnalysis.auto_fixable && latestFailedExec && (
                            <Button type="primary" icon={<ThunderboltOutlined />} onClick={() => handleAutoFix(latestFailedExec.id)}>
                              一键自动修复
                            </Button>
                          )}
                          <Button icon={<EditOutlined />} onClick={() => { setActiveTab('script'); handleEditScript(); }}>
                            手动修改脚本
                          </Button>
                        </Space>
                      </Card>
                    )}

                    {/* AI执行时间线 */}
                    {timelineLoading ? (
                      <div style={{ textAlign: 'center', padding: '12px 0', marginBottom: 16 }}>
                        <Spin size="small" /> <Text type="secondary">加载AI执行时间线...</Text>
                      </div>
                    ) : timeline.length > 0 && (
                      <Card size="small" title={<Space><RobotOutlined /> AI执行时间线</Space>} style={{ marginBottom: 16 }}>
                        <Timeline items={timeline.map((step, i) => {
                          const stepStatus = step.status || 'success';
                          const dot = stepStatus === 'success' ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
                            : stepStatus === 'failed' ? <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
                            : stepStatus === 'running' ? <LoadingOutlined spin style={{ color: '#1890ff' }} />
                            : <InfoCircleOutlined style={{ color: '#d9d9d9' }} />;
                          const tlColor = stepStatus === 'success' ? '#52c41a'
                            : stepStatus === 'failed' ? '#ff4d4f'
                            : stepStatus === 'running' ? '#1890ff'
                            : '#d9d9d9';
                          const collapseItems: Array<{ key: string; label: React.ReactNode; children: React.ReactNode }> = [];
                          if (step.input) {
                            collapseItems.push({
                              key: 'input',
                              label: <Text type="secondary" style={{ fontSize: 12 }}>输入摘要</Text>,
                              children: <pre style={{ fontSize: 12, whiteSpace: 'pre-wrap', margin: 0, background: '#f5f5f5', padding: 8, borderRadius: 4 }}>{typeof step.input === 'string' ? step.input : JSON.stringify(step.input, null, 2)}</pre>,
                            });
                          }
                          if (step.output) {
                            collapseItems.push({
                              key: 'output',
                              label: <Text type="secondary" style={{ fontSize: 12 }}>输出摘要</Text>,
                              children: <pre style={{ fontSize: 12, whiteSpace: 'pre-wrap', margin: 0, background: '#f5f5f5', padding: 8, borderRadius: 4 }}>{typeof step.output === 'string' ? step.output : JSON.stringify(step.output, null, 2)}</pre>,
                            });
                          }
                          return {
                            key: i,
                            dot,
                            color: tlColor,
                            children: (
                              <div>
                                <Space size="small" align="center">
                                  <Text strong>{step.step || step.name || `步骤 ${i + 1}`}</Text>
                                  {step.duration != null && <Text type="secondary" style={{ fontSize: 12 }}>{step.duration}ms</Text>}
                                </Space>
                                {collapseItems.length > 0 && (
                                  <Collapse ghost size="small" style={{ marginTop: 4 }} items={collapseItems} />
                                )}
                              </div>
                            ),
                          };
                        })} />
                      </Card>
                    )}

                    {/* 执行时间轴回放 */}
                    {executionRecords.length > 0 && (
                      <div style={{ marginBottom: 16 }}>
                        <ExecutionTimeline
                          steps={buildTimelineFromExecution(executionRecords[0] as any)}
                          title="最近执行回放"
                        />
                      </div>
                    )}
                    <Table columns={[
                      { title: 'ID', dataIndex: 'id', width: 60 },
                      { title: '状态', dataIndex: 'status', width: 80, render: (s: string) => <StatusTag status={s} size="small" /> },
                      { title: '耗时', dataIndex: 'duration', width: 80, render: (d: number) => d ? `${d.toFixed(1)}s` : '-' },
                      { title: '通过/失败', width: 90, render: (_: any, r: ExecutionRecord) => <span><Text type="success">{r.success_count}</Text>/<Text type="danger">{r.failed_count}</Text></span> },
                      { title: '操作', width: 200, render: (_: any, r: ExecutionRecord) => (
                        <Space size="small">
                          <Button size="small" icon={<FileTextOutlined />} onClick={() => handleViewLog(r)}>日志</Button>
                          {r.screenshot_path && <Button size="small" icon={<CameraOutlined />} onClick={() => handleViewScreenshot(r)}>截图</Button>}
                          {r.report_path && <Button size="small" icon={<EyeOutlined />} onClick={() => handleViewReport(r)}>报告</Button>}
                          <Button size="small" icon={<ReloadOutlined />} onClick={handleExecute}>复现</Button>
                        </Space>
                      )},
                    ]} dataSource={executionRecords} rowKey="id" size="small" pagination={{ pageSize: 10 }} />
                  </div>
                ),
              }] : []),
              ...(hasExecutionResult ? [{
                key: 'result',
                label: '结果',
                children: (
                  <Space direction="vertical" style={{ width: '100%' }} size="middle">
                    <Row gutter={12}>
                      {latestSuccessExec && (
                        <Col span={latestFailedExec ? 12 : 24}>
                          <Card size="small" style={{ borderColor: '#52c41a' }}>
                            <Statistic title="最近成功" value={`#${latestSuccessExec.id}`} prefix={<CheckCircleOutlined style={{ color: '#52c41a' }} />} valueStyle={{ color: '#52c41a' }} />
                            <Descriptions size="small" column={2} style={{ marginTop: 4 }}>
                              <Descriptions.Item label="耗时">{latestSuccessExec.duration?.toFixed(1)}s</Descriptions.Item>
                              <Descriptions.Item label="通过/失败">{latestSuccessExec.success_count}/{latestSuccessExec.failed_count}</Descriptions.Item>
                            </Descriptions>
                          </Card>
                        </Col>
                      )}
                      {latestFailedExec && (
                        <Col span={latestSuccessExec ? 12 : 24}>
                          <Card size="small" style={{ borderColor: '#ff4d4f' }}>
                            <Statistic title="最近失败" value={`#${latestFailedExec.id}`} prefix={<CloseCircleOutlined style={{ color: '#ff4d4f' }} />} valueStyle={{ color: '#ff4d4f' }} />
                            {latestFailedExec.error_message && <Alert type="error" message={latestFailedExec.error_message} style={{ marginTop: 8 }} showIcon />}
                            <Button size="small" icon={<BugOutlined />} style={{ marginTop: 8 }} onClick={() => navigate(`/defect?execution_id=${latestFailedExec.id}`)}>缺陷分析</Button>
                          </Card>
                        </Col>
                      )}
                    </Row>
                    {pageElements.length > 0 && (
                      <Card size="small" title={`页面元素 (${pageElements.length})`}>
                        <Table columns={[
                          { title: '标签', dataIndex: 'tag_name', width: 60, render: (t: string) => <Tag>{t}</Tag> },
                          { title: '文本', dataIndex: 'element_text', ellipsis: true },
                          { title: 'XPath', dataIndex: 'xpath', width: 180, ellipsis: true },
                        ]} dataSource={pageElements} rowKey="id" size="small" pagination={{ pageSize: 15 }} />
                      </Card>
                    )}
                    {latestSuccessExec?.screenshot_path && (
                      <Card size="small" title="执行截图"><AntImage src={getScreenshotUrl(latestSuccessExec.id)} style={{ maxWidth: '100%' }} /></Card>
                    )}
                  </Space>
                ),
              }] : []),
            ]} />
          </Card>
        </Col>

        {/* ===== 右栏：操作面板 ===== */}
        <Col xs={24} lg={6}>
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            {/* 主操作区 */}
            <Card size="small" title="操作">
              <Space direction="vertical" style={{ width: '100%' }} size="small">
                {task.status === 'pending' && (
                  <Button type="primary" block icon={<PlayCircleOutlined />} onClick={startAnalysis}>开始分析</Button>
                )}
                {(task.status === 'success' || task.status === 'processing') && (
                  <Button block icon={<ReloadOutlined />} onClick={handleRerun}>重新分析</Button>
                )}
                {task.status === 'failed' && (
                  <Button type="primary" danger block icon={<ReloadOutlined />} onClick={handleRerun}>重试分析</Button>
                )}
                {task.script && !executing && !analyzing && task.status !== 'pending' && (
                  <Button type="primary" block icon={<ThunderboltOutlined />} onClick={handleExecute}>开始执行</Button>
                )}
                {task.script && (
                  <Button block icon={<DownloadOutlined />} onClick={() => downloadScript(task.id)}>下载脚本</Button>
                )}
                <Divider style={{ margin: '4px 0' }} />
                <Popconfirm title="确认删除此任务？" onConfirm={handleDelete} okText="确定" cancelText="取消">
                  <Button danger block icon={<DeleteOutlined />}>删除任务</Button>
                </Popconfirm>
              </Space>
            </Card>

            {/* AI类型识别结果（只读） */}
            <Card size="small" title={<Space><AppstoreOutlined /> AI类型识别</Space>}>
              <div style={{ textAlign: 'center', padding: '8px 0' }}>
                <Tag color={AI_TYPE_COLORS[taskType] || 'blue'} style={{ fontSize: 14, padding: '4px 12px' }}>
                  {AI_TYPE_ICONS[taskType] || ''} {AI_TYPE_LABELS[taskType] || TASK_TYPE_LABELS[taskType] || 'Web测试'}
                </Tag>
                <div style={{ marginTop: 4 }}>
                  <Text type="secondary" style={{ fontSize: 11 }}>系统根据需求自动识别</Text>
                </div>
              </div>
              {task.test_scope && (
                <div style={{ marginTop: 8 }}>
                  <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>测试范围</Text>
                  <Space size={4} wrap>
                    {Object.entries(task.test_scope).map(([key, val]) => (
                      <Tag key={key} color={val ? AI_TYPE_COLORS[key] : 'default'} style={{ fontSize: 10 }}>
                        {AI_TYPE_ICONS[key]} {AI_TYPE_LABELS[key]}
                      </Tag>
                    ))}
                  </Space>
                </div>
              )}
            </Card>

            {/* 快捷跳转 + 智能建议 */}
            {latestFailedExec && (
              <SmartSuggestion
                executionId={latestFailedExec.id}
                taskId={Number(id)}
                errorMessage={latestFailedExec.error_message || undefined}
                onAutoFix={() => { fetchTask(); fetchExecutions(); }}
                onRerun={handleExecute}
              />
            )}
            {/* 一键复现 & 一键优化 */}
            {task.script && executionRecords.length > 0 && (
              <Card size="small" title="快捷操作">
                <Space direction="vertical" style={{ width: '100%' }} size="small">
                  <Button block icon={<ReloadOutlined />} onClick={handleExecute}>
                    一键复现
                  </Button>
                  <Button block icon={<EditOutlined />} onClick={handleEditScript}>
                    优化脚本
                  </Button>
                </Space>
              </Card>
            )}
          </Space>
        </Col>
      </Row>

      {/* 弹窗 */}
      <Modal title="执行日志" open={logModalVisible} onCancel={() => setLogModalVisible(false)} footer={null} width={800}>
        <pre style={{ background: '#1e1e1e', color: '#d4d4d4', padding: 16, borderRadius: 8, overflow: 'auto', fontSize: 12, maxHeight: 500, whiteSpace: 'pre-wrap' }}>{logContent}</pre>
      </Modal>
      <Modal title="执行截图" open={screenshotModalVisible} onCancel={() => setScreenshotModalVisible(false)} footer={null} width={1000}>
        <AntImage src={screenshotUrl} style={{ width: '100%' }} />
      </Modal>
    </div>
  );
};

export default TaskDetail;
