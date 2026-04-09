import clsx from "clsx";
import type { ButtonHTMLAttributes } from "react";

export function Button({
  children,
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={clsx(
        "inline-flex items-center justify-center rounded-full px-5 py-3 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50",
        "bg-slate-950 text-white hover:bg-slate-800",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}
