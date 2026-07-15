import React, { useEffect } from 'react';
import { Modal, Form, Input, Radio, Space, Typography, Tag, Alert } from 'antd';

const { Text } = Typography;

export interface ReviewQuestion {
  id: number;
  question_text: string;
  question_type: string;
  category: string;
  default_answer: string | null;
  required: boolean;
  options?: string[];
}

interface ReviewModalProps {
  open: boolean;
  questions: ReviewQuestion[];
  onSubmit: (answers: { question_id: number; answer: string }[]) => void;
  onCancel: () => void;
}

const ReviewModal: React.FC<ReviewModalProps> = ({ open, questions, onSubmit, onCancel }) => {
  const [form] = Form.useForm();

  useEffect(() => {
    if (open) {
      // 设置默认值
      const defaults: Record<string, any> = {};
      questions.forEach((q) => {
        if (q.default_answer) {
          defaults[`q_${q.id}`] = q.default_answer;
        }
      });
      form.setFieldsValue(defaults);
    }
  }, [open, questions]);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      const answers = questions.map((q) => ({
        question_id: q.id,
        answer: values[`q_${q.id}`] || '',
      }));
      onSubmit(answers);
    } catch (e) {
      // validation error
    }
  };

  const categoryColors: Record<string, string> = {
    login: 'red',
    permission: 'orange',
    sms: 'volcano',
    captcha: 'gold',
    environment: 'cyan',
    data: 'blue',
    page: 'purple',
    flow: 'geekblue',
    goal: 'green',
    other: 'default',
  };

  return (
    <Modal
      title="AI评审 - 补充信息"
      open={open}
      onOk={handleSubmit}
      onCancel={onCancel}
      okText="提交并继续"
      cancelText="跳过"
      width={600}
    >
      <Alert
        type="info"
        message="AI在评审过程中发现部分信息可能需要补充，请回答以下问题以便生成更准确的测试需求。"
        style={{ marginBottom: 16 }}
      />

      <Form form={form} layout="vertical">
        {questions.map((q, index) => (
          <Form.Item
            key={q.id}
            label={
              <Space>
                <Text strong>{index + 1}. {q.question_text}</Text>
                <Tag color={categoryColors[q.category] || 'default'}>
                  {q.category}
                </Tag>
                {q.required && <Tag color="red">必填</Tag>}
              </Space>
            }
            name={`q_${q.id}`}
            rules={q.required ? [{ required: true, message: '请回答此问题' }] : []}
          >
            {q.question_type === 'boolean' ? (
              <Radio.Group>
                <Radio value="是">是</Radio>
                <Radio value="否">否</Radio>
              </Radio.Group>
            ) : q.question_type === 'choice' && q.options ? (
              <Radio.Group>
                {q.options.map((opt) => (
                  <Radio key={opt} value={opt}>{opt}</Radio>
                ))}
              </Radio.Group>
            ) : (
              <Input.TextArea rows={2} placeholder="请输入回答" />
            )}
          </Form.Item>
        ))}
      </Form>
    </Modal>
  );
};

export default ReviewModal;
