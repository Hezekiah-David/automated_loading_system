from io import BytesIO
import unicodedata
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _pdf_text(value):
    return unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode('ascii')


def create_receipt_pdf(booking, payment):
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=22 * mm,
        leftMargin=22 * mm,
        topMargin=22 * mm,
        bottomMargin=22 * mm,
        title=f'Payment Receipt - Booking {booking.pk}',
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'ReceiptTitle',
        parent=styles['Title'],
        alignment=TA_CENTER,
        textColor=colors.HexColor('#60452f'),
    )
    normal_style = styles['BodyText']

    passenger_name = booking.passenger.get_full_name() or booking.passenger.username
    rows = [
        ('Invoice / payment reference', str(payment.reference)),
        ('Passenger', passenger_name),
        ('Email', booking.passenger.email),
        ('Trip', booking.trip.route.route_name),
        ('Origin', booking.trip.route.origin),
        ('Destination', booking.trip.route.destination),
        ('Seat', str(booking.seat_number)),
        ('Departure', booking.trip.departure_time.strftime('%b %d, %Y %H:%M')),
        ('Payment method', payment.method),
        ('Amount paid', f'NGN {payment.amount:.2f}'),
        ('Paid on', payment.paid_at.strftime('%b %d, %Y %H:%M') if payment.paid_at else ''),
    ]
    table_data = [
        [
            Paragraph(f'<b>{escape(_pdf_text(label))}</b>', normal_style),
            Paragraph(escape(_pdf_text(value)), normal_style),
        ]
        for label, value in rows
    ]
    table = Table(table_data, colWidths=(58 * mm, 108 * mm), hAlign='LEFT')
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f3eee8')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d8cec3')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 9),
        ('RIGHTPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    document.build([
        Paragraph('Payment Receipt &amp; Invoice', title_style),
        Spacer(1, 8 * mm),
        Paragraph(
            f'Payment verified for {escape(_pdf_text(passenger_name))}. '
            'Keep this invoice for your records.',
            normal_style,
        ),
        Spacer(1, 6 * mm),
        table,
    ])
    return buffer.getvalue()
