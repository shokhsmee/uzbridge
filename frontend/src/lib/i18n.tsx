import { createContext, useContext, useState, type ReactNode } from 'react'

export type Lang = 'uz' | 'ru'

const dict = {
  // shell
  'nav.overview': { uz: 'Umumiy', ru: 'Обзор' },
  'nav.integrations': { uz: 'Integratsiyalar', ru: 'Интеграции' },
  'nav.providers': { uz: 'Toʻlov usullari', ru: 'Способы оплаты' },
  'nav.payments': { uz: 'Toʻlovlar', ru: 'Платежи' },
  'nav.logout': { uz: 'Chiqish', ru: 'Выйти' },
  // auth
  'auth.signup.title': { uz: 'Kompaniyangizni ulang', ru: 'Подключите компанию' },
  'auth.signup.lede': {
    uz: 'amoCRM bitimlaridan Payme, Click va Uzum orqali toʻlov qabul qiling.',
    ru: 'Принимайте оплату через Payme, Click и Uzum прямо из сделок amoCRM.',
  },
  'auth.company': { uz: 'Kompaniya nomi', ru: 'Название компании' },
  'auth.slug': { uz: 'Manzil (subdomen)', ru: 'Адрес (поддомен)' },
  'auth.name': { uz: 'Ismingiz', ru: 'Ваше имя' },
  'auth.email': { uz: 'Email', ru: 'Email' },
  'auth.password': { uz: 'Parol', ru: 'Пароль' },
  'auth.create': { uz: 'Kompaniya yaratish', ru: 'Создать компанию' },
  'auth.login': { uz: 'Kirish', ru: 'Войти' },
  'auth.login.title': { uz: 'Hisobga kirish', ru: 'Вход в кабинет' },
  'auth.have_account': { uz: 'Hisobingiz bormi?', ru: 'Уже есть аккаунт?' },
  'auth.no_account': { uz: 'Yangi kompaniyami?', ru: 'Новая компания?' },
  'auth.choose_company': { uz: 'Kompaniyani tanlang', ru: 'Выберите компанию' },
  'auth.slug_free': { uz: 'Boʻsh', ru: 'Свободен' },
  'auth.preparing': { uz: 'Manzilingiz tayyorlanmoqda (xavfsiz ulanish), bir daqiqagacha…', ru: 'Готовим ваш адрес (защищённое соединение), до минуты…' },
  'auth.signing_in': { uz: 'Kirilmoqda…', ru: 'Входим…' },
  // overview
  'ov.title': { uz: 'Umumiy koʻrinish', ru: 'Обзор' },
  'ov.setup': { uz: 'Sozlash', ru: 'Настройка' },
  'ov.step.crm': { uz: 'amoCRM ni ulang', ru: 'Подключите amoCRM' },
  'ov.step.providers': { uz: 'Kamida bitta toʻlov usulini qoʻshing', ru: 'Добавьте хотя бы один способ оплаты' },
  'ov.step.stage': { uz: '“Toʻlandi” bosqichini tanlang', ru: 'Выберите этап «Оплачено»' },
  'ov.step.fiscal': { uz: 'Fiskal chek uchun MXIK kodini kiriting', ru: 'Укажите код ИКПУ для фискального чека' },
  'ov.paid30': { uz: '30 kunda tushum', ru: 'Поступило за 30 дней' },
  'ov.pending': { uz: 'Toʻlov kutilmoqda', ru: 'Ожидает оплаты' },
  'ov.invoices': { uz: 'Hisoblar (30 kun)', ru: 'Счета (30 дней)' },
  'ov.conversion': { uz: 'Toʻlangan', ru: 'Оплачено' },
  'ov.by_provider': { uz: 'Usullar boʻyicha', ru: 'По способам' },
  // integrations
  'int.title': { uz: 'Integratsiyalar', ru: 'Интеграции' },
  'int.lede': { uz: 'Ishlatadigan tizimlaringizni ulang.', ru: 'Подключите системы, в которых вы работаете.' },
  'int.connect': { uz: 'Ulash', ru: 'Подключить' },
  'int.open': { uz: 'Sozlamalar', ru: 'Настройки' },
  'int.soon': { uz: 'Tez orada', ru: 'Скоро' },
  'int.connected': { uz: 'Ulangan', ru: 'Подключено' },
  'int.error': { uz: 'Eʼtibor talab', ru: 'Требует внимания' },
  // amocrm
  'amo.title': { uz: 'amoCRM', ru: 'amoCRM' },
  'amo.lede': {
    uz: 'Toʻliq ruxsatli integratsiya. Menejer bitim kartasidan toʻlov havolasini yaratadi; toʻlovdan soʻng bitim avtomatik “Toʻlandi” bosqichiga oʻtadi.',
    ru: 'Интеграция с полным доступом. Менеджер создаёт ссылку на оплату в карточке сделки; после оплаты сделка сама переходит на этап «Оплачено».',
  },
  'amo.connect': { uz: 'amoCRM ni ulash', ru: 'Подключить amoCRM' },
  'amo.account': { uz: 'Akkaunt', ru: 'Аккаунт' },
  'amo.disconnect': { uz: 'Uzish', ru: 'Отключить' },
  'amo.pipelines': { uz: 'Voronkalar va “Toʻlandi” bosqichi', ru: 'Воронки и этап «Оплачено»' },
  'amo.refresh': { uz: 'Yangilash', ru: 'Обновить' },
  'amo.notes': { uz: 'Bitimga izoh yozish (havola, toʻlov, qaytarish)', ru: 'Писать примечания в сделку (ссылка, оплата, возврат)' },
  'amo.link_field': { uz: 'Havola yoziladigan maydon', ru: 'Поле для ссылки' },
  'amo.status_field': { uz: 'Holat yoziladigan maydon', ru: 'Поле для статуса' },
  'amo.none': { uz: '— yozilmasin —', ru: '— не записывать —' },
  'amo.save': { uz: 'Saqlash', ru: 'Сохранить' },
  'amo.saved': { uz: 'Saqlandi', ru: 'Сохранено' },
  'amo.not_configured': {
    uz: 'Serverda amoCRM integratsiyasi hali sozlanmagan (client_id yoʻq).',
    ru: 'Интеграция amoCRM на сервере ещё не настроена (нет client_id).',
  },
  // providers
  'pr.title': { uz: 'Toʻlov usullari', ru: 'Способы оплаты' },
  'pr.lede': {
    uz: 'Har bir tizim bilan oʻz shartnomangiz boʻladi; pul toʻgʻridan-toʻgʻri hisobingizga tushadi. Kalitlar shifrlangan holda saqlanadi.',
    ru: 'Договор с каждой системой — ваш; деньги идут напрямую на ваш счёт. Ключи хранятся в зашифрованном виде.',
  },
  'pr.enabled': { uz: 'Yoqilgan', ru: 'Включён' },
  'pr.test_mode': { uz: 'Test rejimi', ru: 'Тестовый режим' },
  'pr.callback': { uz: 'Kabinetga qoʻyiladigan callback URL', ru: 'Callback URL для кабинета' },
  'pr.keep': { uz: 'Oʻzgartirmaslik uchun boʻsh qoldiring', ru: 'Оставьте пустым, чтобы не менять' },
  'pr.ready': { uz: 'Tayyor', ru: 'Готово' },
  'pr.incomplete': { uz: 'Toʻliq emas', ru: 'Не заполнено' },
  'pr.fiscal': { uz: 'Fiskal chek (standart qator)', ru: 'Фискальный чек (строка по умолчанию)' },
  'pr.fiscal_lede': {
    uz: 'Bitimda mahsulotlar boʻlmasa, chekka shu MXIK kodi bilan bitta qator yoziladi.',
    ru: 'Если в сделке нет товаров, в чек уходит одна строка с этим кодом ИКПУ.',
  },
  'pr.copy': { uz: 'Nusxa', ru: 'Копировать' },
  'pr.copied': { uz: 'Nusxalandi', ru: 'Скопировано' },
  // payments
  'pay.title': { uz: 'Toʻlovlar', ru: 'Платежи' },
  'pay.new': { uz: 'Yangi hisob', ru: 'Новый счёт' },
  'pay.search': { uz: 'Raqam, bitim yoki izoh', ru: 'Номер, сделка или описание' },
  'pay.all': { uz: 'Hammasi', ru: 'Все' },
  'pay.amount': { uz: 'Summa, soʻm', ru: 'Сумма, сум' },
  'pay.description': { uz: 'Izoh', ru: 'Описание' },
  'pay.create': { uz: 'Havola yaratish', ru: 'Создать ссылку' },
  'pay.cancel': { uz: 'Bekor qilish', ru: 'Отменить' },
  'pay.empty': { uz: 'Hali hisoblar yoʻq.', ru: 'Счетов пока нет.' },
  'pay.lead': { uz: 'Bitim', ru: 'Сделка' },
  'pay.txns': { uz: 'Tranzaksiyalar', ru: 'Транзакции' },
  'pay.crm_sync': { uz: 'amoCRM ga yozildi', ru: 'Записано в amoCRM' },
  'pay.link': { uz: 'Toʻlov havolasi', ru: 'Ссылка на оплату' },
  'status.pending': { uz: 'Kutilmoqda', ru: 'Ожидает' },
  'status.paid': { uz: 'Toʻlandi', ru: 'Оплачен' },
  'status.cancelled': { uz: 'Bekor', ru: 'Отменён' },
  'status.refunded': { uz: 'Qaytarildi', ru: 'Возврат' },
  'common.close': { uz: 'Yopish', ru: 'Закрыть' },
  'common.loading': { uz: 'Yuklanmoqda…', ru: 'Загрузка…' },
} as const

export type Key = keyof typeof dict

const LangCtx = createContext<{ lang: Lang; setLang: (l: Lang) => void }>({ lang: 'uz', setLang: () => {} })

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem('lang')
    if (saved === 'uz' || saved === 'ru') return saved
  } catch {
    /* storage blocked */
  }
  return 'uz'
}

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang)
  const setLang = (l: Lang) => {
    setLangState(l)
    try {
      localStorage.setItem('lang', l)
    } catch {
      /* ignore */
    }
    document.documentElement.lang = l
  }
  return <LangCtx.Provider value={{ lang, setLang }}>{children}</LangCtx.Provider>
}

export function useT() {
  const { lang, setLang } = useContext(LangCtx)
  const t = (k: Key) => dict[k][lang]
  return { t, lang, setLang }
}
