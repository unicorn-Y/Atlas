import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from './cn';

const button = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium transition-[background,color,filter,box-shadow] duration-150 disabled:opacity-45 disabled:pointer-events-none [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        primary: 'primary-fill hover:brightness-[1.06]',
        secondary: 'bg-sunken text-fg shadow-[inset_0_0_0_1px_var(--line)] hover:bg-hover',
        ghost: 'text-fg-2 hover:bg-hover hover:text-fg',
        danger: 'bg-danger-soft text-danger hover:brightness-110',
      },
      size: {
        sm: 'h-7 px-2.5 text-[12.5px] rounded-lg [&_svg]:size-3.5',
        md: 'h-8 px-3.5 text-[13px] rounded-lg [&_svg]:size-4',
        lg: 'h-10 px-5 text-sm rounded-xl [&_svg]:size-4',
        icon: 'size-8 rounded-lg [&_svg]:size-[17px]',
        'icon-sm': 'size-7 rounded-lg [&_svg]:size-4',
      },
    },
    defaultVariants: { variant: 'secondary', size: 'md' },
  },
);

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof button> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, type = 'button', ...props }, ref) =>
  <button ref={ref} type={type} className={cn(button({ variant, size }), className)} {...props} />);
Button.displayName = 'Button';
