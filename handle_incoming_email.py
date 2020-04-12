#!/usr/bin/python
# -*- coding: utf-8 -*-

import logging
import re
import os

from google.appengine.ext.webapp.mail_handlers import InboundMailHandler
from google.appengine.api import mail

import webapp2

DD_MAIL_CODE = os.environ['DD_MAIL_CODE']
USER_EMAIL = os.environ['DD_USER_EMAIL']
BANK_EMAIL = os.environ['BANK_EMAIL']
APPROVED_EMAILS = [USER_EMAIL.lower(), BANK_EMAIL.lower()]


class LogSenderHandler(InboundMailHandler):
    def receive(self, mail_message):
        sender = mail_message.sender.lower()
        if APPROVED_EMAILS[0] not in sender and APPROVED_EMAILS[1] not in sender:
            logging.warn("Parser: sender %s is not approved", mail_message.sender)
            return

        plaintext_bodies = mail_message.bodies('text/plain')

        res = []
        for content_type, body in plaintext_bodies:
            if body.encoding == "binary":
                # "Unknown decoding binary" happens if Content-Transfer-Encoding is set to binary
                plaintext = body.payload
                if body.charset and str(body.charset).lower() != '7bit':
                    plaintext = plaintext.decode(str(body.charset))
            else:
                # Decodes base64 and friends
                plaintext = body.decode()

            v = self.parseAlfabank(plaintext)

            if v:
                res.append(v)
            else:
                logging.warning("Unable to parse mail %s", plaintext)
                mail.send_mail_to_admins(
                    sender=USER_EMAIL,
                    subject="DrebeDengi parser: unable to parse email",
                    body=plaintext)

        if len(res) > 0:
            mail.send_mail_to_admins(sender=USER_EMAIL,
                                     subject="DrebeDengi parser: " + "; ".join(res),
                                     body="Parse result:\n" + "\n".join(res))

            mail.send_mail(sender=USER_EMAIL,
                           to="parser@x-pro.ru",
                           subject="Please parse " + DD_MAIL_CODE,
                           body=DD_MAIL_CODE,
                           attachments=[('lines.txt', "\n".join(res))])

            logging.info("Success result sent to DrebeDengi")
        else:
            logging.warning('Nothing sent to Drebedengi... empty result parsed')

        logging.info("Parse result: %s", "; ".join(res))

    def parseAlfabank(self, txt):
        logging.debug('Text to parse: %s', txt)

        m = re.search(
            ur'Карта (?P<card_num>[0-9.]+)$\n' +
            ur'^.*$\n' +
            ur'^(?P<op_type>.*)$\n' +
            ur'^(?P<op_result>.*)$\n' +
            ur'^Сумма:(?P<amount>[0-9.]+) (?P<currency>\w+)$\n' +
            ur'^Остаток:[0-9.]+ \w+$\n' +
            ur'^На время:(\d\d:\d\d:\d\d)$\n' +
            ur'^(?P<place>[^\r\n]*)$\n' +
            ur'^(?P<day>\d\d)\.(?P<month>\d\d)\.(?P<year>\d{4}) (?P<datetime>\d\d:\d\d:\d\d)',
            txt,
            re.MULTILINE
        )

        if m:
            year = m.group('year')
            month = m.group('month')
            day = m.group('day')
            trx_dt = '%s-%s-%s %s' % (year, month, day, m.group('datetime'))

            op_result = m.group('op_result')
            op_type = m.group('op_type')

            l = [
                '-' + m.group('amount'), #  SUM
                m.group('currency'),  #  CURRENCY
                m.group('place'),  #  OBJECT
                m.group('card_num'),  #  ACCOUNT
                trx_dt, #  DATE
                u' '.join([op_result, op_type]), #  COMMENT
                ''
            ]

            logging.debug('List of tokens: %s', l)
            return ';'.join(l)

        return None


    def parseCitialert(self, txt):
        # m = re.search(ur'')
        m = re.search(ur'Покупка на сумму (?P<summ>[0-9.]+) (?P<currency>\w+) была произведена по Вашему счету \*\*\s*(?P<account>\d+)\s+Торговая точка: (?P<operation>.*?)\s*$\s+Дата операции: (?P<date>\d\d/\d\d/\d\d\d\d)', txt, re.MULTILINE)
        if m:
            return self.result(u"покупка", m.group("summ"), m.group("currency"), m.group("account"), m.group("operation"))

        m = re.search(ur'(?P<summ>[0-9.]+) (?P<currency>\w+) было списано с Вашего счета \*\* ?(?P<account>\d+)\s+Операция: (?P<operation>.*?)\s*$\s+Дата операции: (?P<date>\d\d/\d\d/\d\d\d\d)', txt, re.MULTILINE)
        if m:
            return self.result(u"списание", m.group("summ"), m.group("currency"), m.group("account"), m.group("operation"))

        m = re.search(ur'поручение по переводу денежных средств исполнено:\s+Со счета \*\* ?(?P<account>\d+)\s+Дата: (?P<date>\d\d/\d\d/\d\d\d\d)\s+Сумма: (?P<summ>[0-9.]+) (?P<currency>\w+)', txt, re.MULTILINE)
        if m:
            return self.result(u"списание", m.group("summ"), m.group("currency"), m.group("account"), u"автоплатёж")

        m = re.search(ur'на ваш счет \*\* ?(?P<account>\d+) была зачислена сумма: (?P<summ>[0-9.]+) (?P<currency>\w+)\s+Операция: (?P<operation>.*?)\s*$\s+Дата: (?P<date>\d\d/\d\d/\d\d\d\d)', txt, re.MULTILINE)
        if m:
            return self.result(u"зачисление", m.group("summ"), m.group("currency"), m.group("account"), m.group("operation"))

        return ""

    def result(self, op_type, summ, currency, account, category):
        return u"Тип: " + op_type + u"; Сумма: " + summ + " " + currency + u"; Счёт: " + account + u"; Категория: " + category


app = webapp2.WSGIApplication([LogSenderHandler.mapping()], debug=True)
