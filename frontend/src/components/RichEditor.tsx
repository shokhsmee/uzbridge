import Image from '@tiptap/extension-image'
import { TableKit } from '@tiptap/extension-table'
import TextAlign from '@tiptap/extension-text-align'
import { EditorContent, useEditor, useEditorState } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import type { ReactNode } from 'react'
import { useRef } from 'react'

type Keyword = { key: string; label: string }

/** The on-site document editor: headings, emphasis, lists, alignment, tables, images, {keywords}. */
export function RichEditor({ value, onChange, keywords, disabled }: { value: string; onChange: (html: string) => void; keywords: Keyword[]; disabled?: boolean }) {
  const file = useRef<HTMLInputElement>(null)
  const editor = useEditor({
    extensions: [
      StarterKit.configure({ heading: { levels: [1, 2, 3] } }),
      TextAlign.configure({ types: ['heading', 'paragraph'] }),
      TableKit.configure({ table: { resizable: false } }),
      Image.configure({ allowBase64: true }),
    ],
    content: value || '<h1>Shartnoma № {number}</h1><p>{date}</p><p></p>',
    editable: !disabled,
    onUpdate: ({ editor }) => onChange(editor.getHTML()),
  })
  const s = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      bold: e?.isActive('bold'),
      italic: e?.isActive('italic'),
      underline: e?.isActive('underline'),
      h1: e?.isActive('heading', { level: 1 }),
      h2: e?.isActive('heading', { level: 2 }),
      bullet: e?.isActive('bulletList'),
      ordered: e?.isActive('orderedList'),
      left: e?.isActive({ textAlign: 'left' }),
      center: e?.isActive({ textAlign: 'center' }),
      right: e?.isActive({ textAlign: 'right' }),
      inTable: e?.isActive('table'),
    }),
  })
  if (!editor) return null
  const c = () => editor.chain().focus()

  const addImage = (f: File | undefined) => {
    if (!f) return
    if (f.size > 1_500_000) {
      alert('Rasm 1.5 MB dan kichik boʻlsin / Изображение до 1.5 МБ')
      return
    }
    const reader = new FileReader()
    reader.onload = () => c().setImage({ src: String(reader.result) }).run()
    reader.readAsDataURL(f)
  }

  return (
    <div className="rounded-xl border border-line bg-surface">
      <div className="flex flex-wrap items-center gap-1 border-b border-line p-2">
        <Tool label="Heading 1" on={s?.h1} onClick={() => c().toggleHeading({ level: 1 }).run()}>H1</Tool>
        <Tool label="Heading 2" on={s?.h2} onClick={() => c().toggleHeading({ level: 2 }).run()}>H2</Tool>
        <Sep />
        <Tool label="Bold" on={s?.bold} onClick={() => c().toggleBold().run()}><b>B</b></Tool>
        <Tool label="Italic" on={s?.italic} onClick={() => c().toggleItalic().run()}><i>I</i></Tool>
        <Tool label="Underline" on={s?.underline} onClick={() => c().toggleUnderline().run()}><u>U</u></Tool>
        <Sep />
        <Tool label="Bullet list" on={s?.bullet} onClick={() => c().toggleBulletList().run()}>•</Tool>
        <Tool label="Numbered list" on={s?.ordered} onClick={() => c().toggleOrderedList().run()}>1.</Tool>
        <Sep />
        <Tool label="Align left" on={s?.left} onClick={() => c().setTextAlign('left').run()}>⟸</Tool>
        <Tool label="Align center" on={s?.center} onClick={() => c().setTextAlign('center').run()}>⇔</Tool>
        <Tool label="Align right" on={s?.right} onClick={() => c().setTextAlign('right').run()}>⟹</Tool>
        <Sep />
        <Tool label="Insert table" onClick={() => c().insertTable({ rows: 3, cols: 2, withHeaderRow: false }).run()}>▦</Tool>
        {s?.inTable && (
          <>
            <Tool label="Add row" onClick={() => c().addRowAfter().run()}>+row</Tool>
            <Tool label="Add column" onClick={() => c().addColumnAfter().run()}>+col</Tool>
            <Tool label="Delete table" onClick={() => c().deleteTable().run()}>✕▦</Tool>
          </>
        )}
        <Tool label="Insert image (logo, stamp)" onClick={() => file.current?.click()}>Img</Tool>
        <input ref={file} type="file" accept="image/png,image/jpeg" className="hidden" onChange={(e) => addImage(e.target.files?.[0])} />
        <Sep />
        <select
          aria-label="Insert keyword"
          className="h-8 rounded-md border border-line bg-surface px-2 text-sm"
          value=""
          onChange={(e) => {
            if (e.target.value) c().insertContent(`{${e.target.value}}`).run()
          }}
        >
          <option value="">+ {'{'}kalit{'}'} / ключ</option>
          {keywords.map((k) => (
            <option key={k.key} value={k.key}>
              {`{${k.key}}`} — {k.label}
            </option>
          ))}
        </select>
      </div>
      <EditorContent editor={editor} className="uzb-doc px-8 py-6 min-h-[420px]" />
    </div>
  )
}

function Tool({ children, onClick, on, label }: { children: ReactNode; onClick: () => void; on?: boolean; label: string }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={on}
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
      className={`h-8 min-w-8 rounded-md px-2 text-sm ${on ? 'bg-accent-soft text-accent-ink' : 'text-ink hover:bg-ground'}`}
    >
      {children}
    </button>
  )
}

function Sep() {
  return <span className="mx-1 h-5 w-px bg-line" aria-hidden />
}
