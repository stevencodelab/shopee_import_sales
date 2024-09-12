from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import base64
import csv
import io
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)

try:
    import pytz
except ImportError:
    pytz = None
    _logger.warning("pytz library is not installed. Timezone conversion may not be accurate.")

class SaleImportWizard(models.TransientModel):
    _name = 'sale.import.wizard'
    _description = 'Sale Import Wizard'

    file_data = fields.Binary(string='File CSV', required=True)
    filename = fields.Char(string='Filename')

    def _parse_file(self):
        """
        Parse the CSV file and return a list of dictionaries.
        """
        data = base64.b64decode(self.file_data)
        file_input = io.StringIO(data.decode("utf-8"))
        reader = csv.DictReader(file_input, delimiter=',')
        return list(reader)

    def _parse_datetime(self, date_string):
        """
        Parse date from string format to naive datetime
        """
        if not date_string:
            return False
        
        date_formats = [
            '%d-%m-%Y %H:%M:%S',
            '%Y-%m-%d %H:%M:%S',
            '%d-%m-%Y %H:%M',
            '%Y-%m-%d %H:%M',
            '%d-%m-%Y',
            '%Y-%m-%d',
            '%d/%m/%Y %H:%M:%S',
            '%Y/%m/%d %H:%M:%S',
            '%d/%m/%Y %H:%M',
            '%Y/%m/%d %H:%M',
            '%d/%m/%Y',
            '%Y/%m/%d',
        ]
        
        for fmt in date_formats:
            try:
                dt = datetime.strptime(date_string, fmt)
                return dt  # Return naive datetime
            except ValueError:
                continue
        
        # Handle ISO 8601 format with timezone
        try:
            dt = datetime.fromisoformat(date_string)
            return dt.replace(tzinfo=None)  # Strip timezone info
        except ValueError:
            pass
        
        logger.warning(f"Unable to parse date: {date_string}")
        return False

    def _parse_float(self, value):
        """
        Parse value to float, handling empty cases
        """
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0

    def _get_or_create_partner(self, row):
        """
        Get or create partner based on username
        """
        Partner = self.env['res.partner']
        username = row.get('Username (Pembeli)')
        
        if not username:
            raise ValidationError(_("Username (Pembeli) is required to create or find a partner."))
        
        partner = Partner.search([('name', '=', username)], limit=1)
        if not partner:
            partner_vals = {
                'name': username,
                'phone': row.get('No. Telepon'),
                'street': row.get('Alamat Pengiriman'),
                'city': row.get('Kota/Kabupaten'),
                'state_id': self._get_state_id(row.get('Provinsi')),
            }
            partner = Partner.create(partner_vals)
        return partner

    def _get_state_id(self, state_name):
        """
        Get state ID based on name
        """
        State = self.env['res.country.state']
        state = State.search([('name', '=', state_name)], limit=1)
        return state.id if state else False

    def _get_or_create_product(self, row):
        """
        Get or create product based on SKU
        """
        Product = self.env['product.product']
        product = Product.search([('default_code', '=', row.get('Nomor Referensi SKU'))], limit=1)
        if not product:
            product = Product.create({
                'name': row.get('Nama Produk'),
                'default_code': row.get('Nomor Referensi SKU'),
                'list_price': self._parse_float(row.get('Harga Awal')),
                'weight': self._parse_float(row.get('Berat Produk')),
            })
        return product

    def _create_sale_order(self, row):
        """
        Create or update sale order based on CSV row data
        """
        SaleOrder = self.env['sale.order']
        order = SaleOrder.search([('nomor_pesanan', '=', row.get('No. Pesanan'))], limit=1)
        
        partner = self._get_or_create_partner(row)
        
        order_vals = {
            'partner_id': partner.id,
            'nomor_pesanan': row.get('No. Pesanan'),
            'order_status': row.get('Status Pesanan'),
            'cancellation_return_status': row.get('Status Pembatalan/ Pengembalian'),
            'tracking_number': row.get('No. Resi'),
            'opsi_pengiriman': row.get('Opsi Pengiriman'),
            'shipping_option': 'antar counter' if row.get('Antar ke counter/pick-up') == 'Antar Ke Counter' else 'pickup',
            'must_ship_before': self._parse_datetime(row.get('Pesanan Harus Dikirimkan Sebelum')),
            'order_creation_time': self._parse_datetime(row.get('Waktu Pesanan Dibuat')),
            'payment_time': self._parse_datetime(row.get('Waktu Pembayaran Dilakukan')),
            'payment_method': row.get('Metode Pembayaran'),
            'seller_discount': self._parse_float(row.get('Diskon Dari Penjual')),
            'platform_discount': self._parse_float(row.get('Diskon Dari Shopee')),
            'voucher_seller': self._parse_float(row.get('Voucher Ditanggung Penjual')),
            'cashback': self._parse_float(row.get('Cashback Koin')),
            'voucher_platform': self._parse_float(row.get('Voucher Ditanggung Shopee')),
            'package_discount': self._parse_float(row.get('Paket Diskon')),
            'package_discount_platform': self._parse_float(row.get('Paket Diskon (Diskon dari Shopee)')),
            'package_discount_seller': self._parse_float(row.get('Paket Diskon (Diskon dari Penjual)')),
            'coin_discount': self._parse_float(row.get('Potongan Koin Shopee')),
            'credit_card_discount': self._parse_float(row.get('Diskon Kartu Kredit')),
            'shipping_fee_paid_by_buyer': self._parse_float(row.get('Ongkos Kirim Dibayar oleh Pembeli')),
            'shipping_fee_discount': self._parse_float(row.get('Estimasi Potongan Biaya Pengiriman')),
            'return_shipping_fee': self._parse_float(row.get('Ongkos Kirim Pengembalian Barang')),
            'estimated_shipping_fee': self._parse_float(row.get('Perkiraan Ongkos Kirim')),
            'buyer_note': row.get('Catatan dari Pembeli'),
            'buyer_username': row.get('Username (Pembeli)'),
            'receiver_name': row.get('Nama Penerima'),
            'receiver_phone': row.get('No. Telepon'),
            'shipping_address': row.get('Alamat Pengiriman'),
            'city': row.get('Kota/Kabupaten'),
            'province': row.get('Provinsi'),
            'order_completion_time': self._parse_datetime(row.get('Waktu Pesanan Selesai')),
        }

        if order:
            order.write(order_vals)
        else:
            order = SaleOrder.create(order_vals)

        # Process order lines
        product = self._get_or_create_product(row)
        line_vals = {
            'order_id': order.id,
            'product_id': product.id,
            'parent_sku': row.get('SKU Induk'),
            'sku_reference': row.get('Nomor Referensi SKU'),
            'variation_name': row.get('Nama Variasi'),
            'original_price': self._parse_float(row.get('Harga Awal')),
            'discounted_price': self._parse_float(row.get('Harga Setelah Diskon')),
            'returned_quantity': self._parse_float(row.get('Returned Quantity', 0.0)),
            'product_uom_qty': self._parse_float(row.get('Jumlah')),
            'product_weight': self._parse_float(row.get('Berat Produk')),
            'total_weight': self._parse_float(row.get('Total Berat')),
        }
        order.order_line = [(0, 0, line_vals)]

        return order

    def import_sales(self):
        """
        Import sales from the uploaded CSV file.
        """
        self.ensure_one()
        if not self.file_data:
            raise UserError(_("Please upload a file to import."))

        rows = self._parse_file()
        created_orders = self.env['sale.order']
        errors = []

        for index, row in enumerate(rows, start=1):
            try:
                order = self._create_sale_order(row)
                created_orders |= order
            except ValidationError as e:
                errors.append(f"Row {index}: Validation error - {str(e)}")
            except Exception as e:
                errors.append(f"Row {index}: Unexpected error - {str(e)}")
                _logger.error(f"Error processing row {index}", exc_info=True)

        if errors:
            error_message = "\n".join(errors)
            if len(created_orders) > 0:
                self.env.cr.rollback()
                message = _(
                    "The import process encountered errors and was rolled back. "
                    "No orders were created. Please fix the following errors and try again:\n%s"
                ) % error_message
            else:
                message = _("The following errors occurred during import:\n%s") % error_message
            raise UserError(message)

        return {
            'name': _('Imported Sale Orders'),
            'view_mode': 'tree,form',
            'res_model': 'sale.order',
            'type': 'ir.actions.act_window',
            'domain': [('id', 'in', created_orders.ids)],
        }