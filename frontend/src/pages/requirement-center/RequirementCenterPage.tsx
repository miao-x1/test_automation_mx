import React, { useState, useCallback, useRef } from 'react';
import {
  Card,
  Steps,
  message,
  Typography,
} from 'antd';
import { useNavigate } from 'react-router-dom';
import InputPanel, { InputPanelHandle } from './InputPanel';
import AnalysisTimeline, { TimelineStep } from './AnalysisTimeline';
import ResultPanel from './ResultPanel';
import ReviewModal, { ReviewQuestion } from './ReviewModal';
import {
  createSession,
  uploadFiles,
  analyzeStream,
  submitReview,
  finalizeRequirement,
  RequirementSummaryData,
} from '../../services/requirementCenter';

const RequirementCenterPage: React.FC = () => {
  const navigate = useNavigate();
  const [analyzing, setAnalyzing] = useState(false);
  const [steps, setSteps] = useState<TimelineStep[]>([]);
  const [summary, setSummary] = useState<RequirementSummaryData | null>(null);
  const [reviewQuestions, setReviewQuestions] = useState<ReviewQuestion[]>([]);
  const [reviewModalOpen, setReviewModalOpen] = useState(false);
  const [finalized, setFinalized] = useState(false);
  const [finalizing, setFinalizing] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [showInput, setShowInput] = useState(true);
  const inputPanelRef = useRef<InputPanelHandle>(null);
  const sessionIdRef = useRef<number | null>(null);

  const handleStartAnalyze = useCallback(async () => {
    try {
      setAnalyzing(true);
      setSteps([]);
      setSummary(null);
      setReviewQuestions([]);
      setFinalized(false);
      setCurrentStep(0);

      // Get data from InputPanel via ref
      const panelData = inputPanelRef.current?.getData();
      if (!panelData) {
        message.error('无法获取输入数据');
        setAnalyzing(false);
        return;
      }

      const { text, urls, context, imageFiles, docFiles, videoFiles, schemaFiles } = panelData;

      // 1. Create Session
      message.loading({ content: '创建分析会话...', key: 'analyze', duration: 1 });
      const sessionRes: any = await createSession({
        title: text ? text.substring(0, 50) : 'AI需求分析',
        input_text: text,
        input_urls: urls,
        system_name: context.system_name,
        business_background: context.business_background,
        test_scope: context.test_scope,
        credentials: context.credentials,
        notes: context.notes,
        special_requirements: context.special_requirements,
      });

      if (sessionRes.code !== 0) {
        message.error('创建会话失败: ' + (sessionRes.message || ''));
        setAnalyzing(false);
        return;
      }

      const sid = sessionRes.data.session_id;
      sessionIdRef.current = sid;

      // 2. Upload files
      const allFiles = [...imageFiles, ...docFiles, ...videoFiles, ...schemaFiles];
      if (allFiles.length > 0) {
        message.loading({ content: '上传文件中...', key: 'analyze', duration: 1 });
        const fileObjects = allFiles
          .map((f: any) => f.originFileObj)
          .filter((f: any) => f instanceof File);
        if (fileObjects.length > 0) {
          await uploadFiles(sid, fileObjects);
        }
      }

      // 3. Start SSE analysis
      message.loading({ content: 'AI开始理解需求...', key: 'analyze', duration: 1 });
      setShowInput(false);

      const stepMap: Record<string, TimelineStep> = {};
      let needsInput = false;
      let questions: ReviewQuestion[] = [];

      for await (const event of analyzeStream(sid)) {
        if (!event || !event.event) continue;
        const { event: eventType, data } = event;

        switch (eventType) {
          case 'step_start': {
            const step: TimelineStep = {
              name: data.name,
              display: data.display || data.name,
              status: 'running',
              started_at: Date.now() / 1000,
            };
            stepMap[data.name] = step;
            setSteps((prev) => [...prev, step]);
            setCurrentStep((prev) => prev + 1);
            break;
          }
          case 'step_completed': {
            const step = stepMap[data.name];
            if (step) {
              step.status = 'completed';
              step.duration = data.duration;
              step.output = data.output;
            }
            setSteps((prev) => [...prev]);
            break;
          }
          case 'step_failed': {
            const step = stepMap[data.name];
            if (step) {
              step.status = 'failed';
              step.duration = data.duration;
              step.error = data.error;
            }
            setSteps((prev) => [...prev]);
            break;
          }
          case 'needs_input': {
            needsInput = true;
            questions = data.questions || [];
            setReviewQuestions(questions);
            break;
          }
          case 'analyzed': {
            if (data.summary) {
              setSummary(data.summary as RequirementSummaryData);
            }
            break;
          }
          case 'error': {
            message.error(data.message || '分析失败');
            break;
          }
          case 'done': {
            if (data.summary) {
              setSummary(data.summary as RequirementSummaryData);
            }
            break;
          }
        }
      }

      message.success({ content: 'AI分析完成', key: 'analyze' });

      if (needsInput && questions.length > 0) {
        setReviewModalOpen(true);
      }

      setAnalyzing(false);
    } catch (error: any) {
      console.error('Analyze error:', error);
      message.error('分析失败: ' + (error.message || ''));
      setAnalyzing(false);
    }
  }, []);

  const handleReviewSubmit = async (answers: { question_id: number; answer: string }[]) => {
    const sid = sessionIdRef.current;
    if (!sid) return;
    try {
      await submitReview(sid, answers);
      setReviewModalOpen(false);
      message.success('评审回答已提交');
    } catch (error: any) {
      message.error('提交失败: ' + (error.message || ''));
    }
  };

  const handleFinalize = async (requirement: string) => {
    const sid = sessionIdRef.current;
    if (!sid) return;
    setFinalizing(true);
    try {
      const res: any = await finalizeRequirement(sid, requirement);
      if (res.code === 0) {
        message.success('需求已确认，任务已创建');
        setFinalized(true);
        if (res.data?.redirect) {
          setTimeout(() => {
            navigate(res.data.redirect);
          }, 1500);
        }
      } else {
        message.error('最终化失败: ' + (res.message || ''));
      }
    } catch (error: any) {
      message.error('最终化失败: ' + (error.message || ''));
    } finally {
      setFinalizing(false);
    }
  };

  return (
    <div>
      <Typography.Title level={3} style={{ marginBottom: 16 }}>需求中心</Typography.Title>

      {/* Step indicator */}
      <Card style={{ marginBottom: 16 }}>
        <Steps
          current={currentStep}
          size="small"
          items={[
            { title: '输入需求' },
            { title: 'AI理解' },
            { title: 'AI评审' },
            { title: '确认创建' },
          ]}
        />
      </Card>

      {/* Input panel - shown when not analyzing and no summary */}
      {showInput && !analyzing && !summary && (
        <InputPanel
          ref={inputPanelRef}
          onStartAnalyze={handleStartAnalyze}
          analyzing={analyzing}
        />
      )}

      {/* Analysis timeline - shown during analysis or when steps exist */}
      {(analyzing || steps.length > 0) && (
        <AnalysisTimeline
          steps={steps}
          analyzing={analyzing}
          result={summary ? { summary } : null}
          reviewQuestions={reviewQuestions}
        />
      )}

      {/* Result panel - shown when summary is available */}
      {summary && (
        <ResultPanel
          summary={summary}
          finalized={finalized}
          onFinalize={handleFinalize}
          finalizing={finalizing}
        />
      )}

      {/* Review modal */}
      <ReviewModal
        open={reviewModalOpen}
        questions={reviewQuestions}
        onSubmit={handleReviewSubmit}
        onCancel={() => setReviewModalOpen(false)}
      />
    </div>
  );
};

export default RequirementCenterPage;
