import { describe, it, expect } from 'vitest';
import { cn } from '../utils';

describe('cn utility function', () => {
  it('should merge basic classes correctly', () => {
    // Tests basic string concatenation behavior of clsx
    expect(cn('class1', 'class2')).toBe('class1 class2');
  });

  it('should handle conditional classes using objects', () => {
    // Tests clsx ability to include keys only if their values are truthy
    expect(cn({ 'class1': true, 'class2': false, 'class3': true })).toBe('class1 class3');
  });

  it('should handle undefined and null inputs without throwing', () => {
    // Tests clsx handling of falsy values commonly passed in React props
    expect(cn('class1', undefined, null, 'class2')).toBe('class1 class2');
  });

  it('should merge tailwind classes properly', () => {
    // Tests twMerge's ability to resolve conflicting tailwind classes (later ones should win)
    expect(cn('p-4', 'p-8')).toBe('p-8');
    expect(cn('text-red-500', 'text-blue-500')).toBe('text-blue-500');
  });

  it('should handle arrays of classes', () => {
    // Tests clsx ability to flatten array inputs
    expect(cn(['class1', 'class2'], 'class3')).toBe('class1 class2 class3');
  });

  it('should properly merge tailwind and non-tailwind classes', () => {
    // Tests combination of standard classes and tailwind classes
    expect(cn('custom-class', 'p-4', 'p-8')).toBe('custom-class p-8');
  });
});
