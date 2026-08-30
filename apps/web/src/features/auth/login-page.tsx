import { LockKeyhole, ShieldCheck } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export interface LoginPageProps {
  onLogin(username: string, password: string): Promise<void> | void;
  pending: boolean;
  error: string | null;
}

export function LoginPage({ onLogin, pending, error }: LoginPageProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (pending) return;
    void onLogin(username, password);
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-950 px-4 py-10 text-slate-100">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_20%_15%,rgba(251,191,36,0.16),transparent_34%),radial-gradient(circle_at_80%_75%,rgba(59,130,246,0.12),transparent_38%)]" />
      <Card className="relative w-full max-w-md border-white/10 bg-slate-900/90 text-slate-100 shadow-2xl shadow-black/40 backdrop-blur-xl">
        <CardHeader className="space-y-5 text-center">
          <div className="mx-auto flex size-14 items-center justify-center rounded-2xl bg-amber-400 text-slate-950 shadow-lg shadow-amber-400/20">
            <LockKeyhole aria-hidden="true" className="size-6" />
          </div>
          <div>
            <p className="text-xs font-semibold tracking-[0.22em] text-amber-300 uppercase">
              观势 · 知势 · 策势
            </p>
            <CardTitle className="mt-2 text-2xl">
              <h1>登录昆仑智策</h1>
            </CardTitle>
            <CardDescription className="mt-2 text-slate-400">
              使用本机初始化的管理员账户进入研究终端
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <form className="space-y-5" onSubmit={submit}>
            <div className="space-y-2">
              <Label htmlFor="kunlun-username">用户名</Label>
              <Input
                id="kunlun-username"
                name="username"
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                disabled={pending}
                required
                minLength={3}
                maxLength={80}
                className="border-white/10 bg-slate-950/60 text-slate-100"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="kunlun-password">密码</Label>
              <Input
                id="kunlun-password"
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                disabled={pending}
                required
                minLength={12}
                maxLength={256}
                className="border-white/10 bg-slate-950/60 text-slate-100"
              />
            </div>
            {error !== null && (
              <p
                role="alert"
                className="rounded-xl border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-200"
              >
                {error}
              </p>
            )}
            <Button
              type="submit"
              disabled={pending || username.length === 0 || password.length === 0}
              className="w-full bg-amber-400 text-center text-slate-950 hover:bg-amber-300"
            >
              {pending ? "正在验证…" : "登录"}
            </Button>
          </form>
          <div className="mt-6 flex items-center justify-center gap-2 border-t border-white/10 pt-5 text-xs text-slate-400">
            <ShieldCheck aria-hidden="true" className="size-4 text-emerald-400" />
            <span>研究与模拟环境 · 无真实下单路径</span>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}
