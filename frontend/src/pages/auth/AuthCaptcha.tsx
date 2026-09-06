import { Input } from 'antd';
import { getCaptcha, type CaptchaPayload } from '../../services/auth';

export default function AuthCaptcha({
  value,
  onChange,
  captcha,
  onRefresh,
}: {
  value?: string;
  onChange?: (value: string) => void;
  captcha: CaptchaPayload | null;
  onRefresh: () => void;
}) {
  return (
    <div style={{ display: 'flex', gap: 8 }}>
      <Input
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        placeholder="图形验证码"
        maxLength={6}
      />
      <button
        type="button"
        onClick={onRefresh}
        title="点击刷新"
        style={{
          width: 140,
          height: 32,
          padding: 0,
          border: '1px solid #ddd6cd',
          borderRadius: 6,
          background: '#f6f3ee',
          cursor: 'pointer',
          overflow: 'hidden',
        }}
      >
        {captcha?.image ? (
          <img src={captcha.image} alt="验证码" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        ) : (
          '加载中'
        )}
      </button>
    </div>
  );
}

export async function loadCaptcha(): Promise<CaptchaPayload> {
  return getCaptcha();
}
