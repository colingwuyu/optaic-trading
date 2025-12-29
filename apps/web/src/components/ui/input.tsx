import * as React from "react";

import { cn } from "@/lib/utils";

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => (
    <input
      type={type}
      ref={ref}
      className={cn(
        "flex h-10 w-full rounded-lg border border-fog-200 bg-white px-3 py-2 text-sm shadow-sm placeholder:text-ink-700/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink-800/30",
        className,
      )}
      {...props}
    />
  ),
);

Input.displayName = "Input";
