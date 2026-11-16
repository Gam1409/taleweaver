import js from '@eslint/js'
import vue from 'eslint-plugin-vue'
import globals from 'globals'
import { configureVueProject, defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'
import skipFormatting from '@vue/eslint-config-prettier/skip-formatting'

configureVueProject({ scriptLangs: ['ts', 'js'], tsSyntaxInTemplates: true })

export default defineConfigWithVueTs(
  { ignores: ['dist/**', 'node_modules/**'] },
  js.configs.recommended,
  vue.configs['flat/essential'],
  vueTsConfigs.base,
  vueTsConfigs.eslintRecommended,
  {
    files: ['**/*.{js,mjs,cjs,ts,tsx,vue}'],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    rules: {
      'vue/multi-word-component-names': 'off',
      'no-console': process.env.NODE_ENV === 'production' ? 'warn' : 'off',
      'no-debugger': process.env.NODE_ENV === 'production' ? 'warn' : 'off'
    }
  },
  {
    files: ['**/*.{ts,tsx,vue}'],
    rules: { 'no-unused-vars': 'off', 'no-undef': 'off', '@typescript-eslint/no-unused-vars': 'warn' }
  },
  skipFormatting
)
