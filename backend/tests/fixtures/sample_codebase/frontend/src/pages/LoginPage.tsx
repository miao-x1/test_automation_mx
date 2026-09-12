import { useState } from 'react';

export function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  const handleLogin = async () => {
    await fetch('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
  };

  return (
    <form>
      <input value={username} onChange={(e) => setUsername(e.target.value)} />
      <input value={password} onChange={(e) => setPassword(e.target.value)} />
      <button type="button" onClick={handleLogin}>登录</button>
    </form>
  );
}
