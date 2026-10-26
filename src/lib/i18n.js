const STORAGE_KEY = 'fet_lang';

const dict = {
  en: {
    settings: 'Settings',
    settingsSubtitle: 'Get support, invite friends and check for app updates',
    customerCare: 'Customer Care',
    customerCareSubtitle: 'Send a message to our support team',
    topic: 'Topic',
    generalInquiry: 'General inquiry',
    accountLogin: 'Account / Login',
    attendance: 'Attendance',
    feesPayments: 'Fees / Payments',
    technicalIssue: 'Technical issue',
    feedback: 'Feedback',
    message: 'Message',
    minimum10: 'Minimum 10 characters',
    chars: 'characters',
    sendMessage: 'Send Message',
    sending: 'Sending...',
    messageSent: 'Message sent successfully. Our team will get back to you soon.',
    couldNotSend: 'Could not send message. Try again.',
    inviteFriend: 'Invite a Friend',
    inviteSubtitle: 'Share your invite link and earn rewards when they join',
    howItWorks: 'How it works',
    inviteDesc: 'Share your unique link with friends. When they sign up using your link, you\'ll be rewarded. Admins can track referrals for reward distribution.',
    yourInviteLink: 'Your Invite Link',
    copyShare: 'Copy / Share',
    copied: 'Copied!',
    invitesSent: 'Invites Sent',
    successfulSignups: 'Successful Signups',
    referralCode: 'Referral code',
    appUpdate: 'App Update',
    appUpdateSubtitle: 'Manually check for a newer version of the platform',
    forceUpdate: 'Force update check',
    forceUpdateDesc: 'If the update pop-up didn\'t appear after a new deployment, use this to check and reload to the latest version.',
    currentSession: 'Current session',
    appBuild: 'App build',
    checkForUpdates: 'Check for updates',
    checking: 'Checking...',
    newVersion: 'A new version is available. Reloading...',
    upToDate: "You're up to date.",
    couldNotCheck: 'Could not check for updates. Try reloading the page.',
    language: 'Language',
    languageSubtitle: 'Choose your preferred language',
    systemLanguage: 'System Language',
    english: 'English',
    french: 'Français',
    languageSaved: 'Your language preference is saved on this device.',
  },
  fr: {
    settings: 'Paramètres',
    settingsSubtitle: "Obtenir de l'aide, inviter des amis et vérifier les mises à jour",
    customerCare: 'Service Client',
    customerCareSubtitle: "Envoyer un message à notre équipe de support",
    topic: 'Sujet',
    generalInquiry: 'Demande générale',
    accountLogin: 'Compte / Connexion',
    attendance: 'Présence',
    feesPayments: 'Frais / Paiements',
    technicalIssue: 'Problème technique',
    feedback: 'Commentaires',
    message: 'Message',
    minimum10: 'Minimum 10 caractères',
    chars: 'caractères',
    sendMessage: 'Envoyer le message',
    sending: 'Envoi...',
    messageSent: "Message envoyé avec succès. Notre équipe vous répondra bientôt.",
    couldNotSend: "Impossible d'envoyer le message. Réessayez.",
    inviteFriend: 'Inviter un ami',
    inviteSubtitle: "Partagez votre lien d'invitation et gagnez des récompenses lorsqu'ils s'inscrivent",
    howItWorks: 'Comment ça fonctionne',
    inviteDesc: "Partagez votre lien unique avec vos amis. Lorsqu'ils s'inscrivent via votre lien, vous serez récompensé. Les administrateurs peuvent suivre les parrainages pour la distribution des récompenses.",
    yourInviteLink: "Votre lien d'invitation",
    copyShare: 'Copier / Partager',
    copied: 'Copié !',
    invitesSent: "Invitations envoyées",
    successfulSignups: "Inscriptions réussies",
    referralCode: 'Code de parrainage',
    appUpdate: "Mise à jour de l'application",
    appUpdateSubtitle: "Vérifier manuellement une version plus récente de la plateforme",
    forceUpdate: "Vérification forcée des mises à jour",
    forceUpdateDesc: "Si la fenêtre de mise à jour n'apparaît pas après un nouveau déploiement, utilisez ceci pour vérifier et recharger vers la dernière version.",
    currentSession: 'Session actuelle',
    appBuild: "Version de l'application",
    checkForUpdates: 'Vérifier les mises à jour',
    checking: 'Vérification...',
    newVersion: 'Une nouvelle version est disponible. Rechargement...',
    upToDate: 'Vous êtes à jour.',
    couldNotCheck: "Impossible de vérifier les mises à jour. Essayez de recharger la page.",
    language: 'Langue',
    languageSubtitle: "Choisissez votre langue préférée",
    systemLanguage: 'Langue du système',
    english: 'Anglais',
    french: 'Français',
    languageSaved: 'Votre préférence de langue est enregistrée sur cet appareil.',
  },
};

export const getLang = () => {
  try {
    const v = localStorage.getItem(STORAGE_KEY) || 'en';
    return v === 'fr' ? 'fr' : 'en';
  } catch {
    return 'en';
  }
};

export const setLang = (v) => {
  const lang = v === 'fr' ? 'fr' : 'en';
  try {
    localStorage.setItem(STORAGE_KEY, lang);
    document.documentElement.lang = lang;
  } catch {
    /* ignore */
  }
  return lang;
};

export const t = (key) => {
  const lang = getLang();
  return dict[lang]?.[key] ?? dict.en[key] ?? key;
};

export default { getLang, setLang, t };
