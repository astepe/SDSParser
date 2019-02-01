import re
import os
import csv
import io
import argparse
from pdfminer.converter import TextConverter
from pdfminer.pdfinterp import PDFPageInterpreter
from pdfminer.pdfinterp import PDFResourceManager
from pdfminer.pdfpage import PDFPage, PDFTextExtractionNotAllowed
from pdf2image import convert_from_path
from pytesseract import image_to_string
from PIL import Image
import progressbar
import tempfile
from .configs import SDSRegexes, Configs


class SDSParser:

    def __init__(self, request_keys=None, debug=False):
        """
        define a set of data request keys
        """

        if request_keys is not None:
            self.request_keys = request_keys
        else:
            self.request_keys = Configs.REQUEST_KEYS

        self.ocr_override = True
        self.ocr_ran = False
        self.force_ocr = False
        self.debug = debug

    @staticmethod
    def find_matching_text_file(sds_file_path, sds_text_files):
        """
        find txt file with same name as sds file
        and return the path to the txt file if found
        """
        sds_file_name = sds_file_path.split('.')[0].split('/')[-1]
        for text_file in os.listdir(sds_text_files):
            if text_file.startswith(sds_file_name):
                return os.path.join(sds_text_files, text_file)
        return None

    @staticmethod
    def get_text_from_file(text_file_path):
        with open(text_file_path, 'r') as text_file:
            return text_file.read()

    def get_sds_data(self, sds_file_path, extract_method=None):
        """
        retrieve requested sds data
        """

        self.reset_state()
        self.define_extract_method(extract_method)

        self.sds_text = self.get_sds_text(sds_file_path)

        manufacturer = self.get_manufacturer(self.sds_text)

        regexes = SDSParser.define_regexes(manufacturer)

        sds_data = self.search_sds_text(self.sds_text, regexes)

        data_not_listed = SDSParser.check_empty_matches(sds_data)

        if data_not_listed and not self.ocr_ran and self.ocr_override:
            print(f'No matches found in {sds_file_path}. Performing ocr...')
            sds_data = self.get_sds_data(sds_file_path, extract_method='ocr')

        if self.debug:
            file_info = {'manufacturer': manufacturer,
                         'sds_file_path': sds_file_path}
            sds_data = SDSParser.add_file_info(sds_data, file_info)

        return sds_data

    @staticmethod
    def add_file_info(sds_data, file_info):
        sds_data['format'] = file_info['manufacturer']
        sds_file_path = file_info['sds_file_path']
        sds_data['filename'] = sds_file_path.split('/')[-1]
        text_file_path = SDSParser.find_matching_text_file(sds_file_path,
                                                           Configs.SDS_TEXT_FILES)
        if text_file_path is not None:
            _ocr_ran = 'ocr' in text_file_path.split('/')[-1]
        else:
            _ocr_ran = self.ocr_ran
        sds_data['extract method'] = 'ocr' if _ocr_ran else 'text'

        return sds_data

    def define_extract_method(self, extract_method):
        if extract_method == 'ocr':
            self.force_ocr = True
        if extract_method == 'text':
            self.ocr_override = False

    def reset_state(self):
        self.ocr_override = True
        self.ocr_ran = False
        self.force_ocr = False

    def define_regexes(manufacturer):

        if manufacturer is not None:
            return SDSParser.compile_regexes(SDSRegexes.SDS_FORMAT_REGEXES[manufacturer])
        else:
            return SDSParser.compile_regexes(SDSRegexes.DEFAULT_SDS_FORMAT)

    def search_sds_text(self, sds_text, regexes):
        """
        construct a dictionary by iterating over each data request and
        performing a regular expression match
        """

        sds_data = {}

        for request_key in self.request_keys:

            if request_key in regexes:

                regex = regexes[request_key]
                match = SDSParser.find_match(sds_text, regex)

                sds_data[request_key] = match

        return sds_data

    @staticmethod
    def check_empty_matches(sds_data):
        """
        check if data not listed
        """

        for _, data in sds_data.items():
            if data.lower() != 'data not listed':
                return False
        return True

    @staticmethod
    def get_match_string(matches):
        """
        retrieve matched group string
        """

        group_matches = 0
        match_string = ''

        for name, group in matches.groupdict().items():
            if group is not None:

                group = group.replace('\n', '').strip()

                if group_matches > 0:
                    match_string += ', ' + group
                else:
                    match_string += group

                group_matches += 1

        if match_string:
            return match_string
        else:
            return 'No data available'

    @staticmethod
    def find_match(sds_text, regex):
        """
        perform a regular expression match and return matched data
        """

        matches = regex.search(sds_text)

        if matches is not None:

            return SDSParser.get_match_string(matches)

        else:

            return 'Data not listed'

    @staticmethod
    def get_manufacturer(sds_text):
        """
        define set of regular expressions to be used for data matching by searching
        for the manufacturer name within the sds text
        """

        for manufacturer, regexes in SDSRegexes.SDS_FORMAT_REGEXES.items():

            regex = re.compile(*regexes['manufacturer'])

            match = regex.search(sds_text)

            if match:
                print(f'using {manufacturer} format...')
                return manufacturer

        print('using default sds format...')
        return None

    @staticmethod
    def compile_regexes(regexes):
        """
        return a dictionary of compiled regular expressions
        """

        compiled_regexes = {}

        for name, regex in regexes.items():

            compiled_regexes[name] = re.compile(*regex)

        return compiled_regexes

    def get_sds_text(self, sds_file_path):
        """
        execute the text extraction function corresponding to the
        specified extract method
        """

        if self.debug:
            text_file_path = SDSParser.find_matching_text_file(sds_file_path,
                                                               Configs.SDS_TEXT_FILES)
            if text_file_path is not None:
                return SDSParser.get_text_from_file(text_file_path)

        if self.force_ocr is True:
            sds_text = SDSParser.get_sds_image_text(sds_file_path)
            self.ocr_ran = True
        else:
            sds_text = SDSParser.get_sds_pdf_text(sds_file_path)
            if sds_text == '' and self.ocr_override and not self.ocr_ran:
                print(f'No text extracted from {sds_file_path}. Performing ocr...')
                sds_text = SDSParser.get_sds_image_text(sds_file_path)
                self.ocr_ran = True

        return sds_text

    @staticmethod
    def get_sds_pdf_text(sds_file_path):
        """
        extract text directly from pdf file
        """

        text = ''
        resource_manager = PDFResourceManager()
        fake_file_handle = io.StringIO()
        converter = TextConverter(resource_manager, fake_file_handle)
        page_interpreter = PDFPageInterpreter(resource_manager, converter)

        try:
            with open(sds_file_path, 'rb') as fh:
                for page in PDFPage.get_pages(fh,
                                              caching=True,
                                              check_extractable=True):
                    page_interpreter.process_page(page)

                text = fake_file_handle.getvalue()

        except PDFTextExtractionNotAllowed:
            pass
        # close open handles
        converter.close()
        fake_file_handle.close()

        return text

    def get_sorted_dir_list(path):

        dir_list = os.listdir(path)
        regex = re.compile(r"[\d]*(?=\.jpg)")
        dir_list.sort(key=lambda x: regex.search(x)[0])
        return dir_list

    @staticmethod
    def get_sds_image_text(sds_file_path):
        """
        extract text from pdf file by applying ocr
        """

        print('=======================================================')
        print('Processing:', sds_file_path.split('/')[-1] + '...')

        with tempfile.TemporaryDirectory() as path:

            page_images = convert_from_path(sds_file_path, fmt='jpeg', output_folder=path, dpi=450)
            dir_list = get_sorted_dir_list(path)

            # initialize progress bar
            progress_bar = progressbar.ProgressBar().start()
            num_pages = len(dir_list)

            sds_image_text = ''
            for idx, page_image in enumerate(dir_list):

                _temp_path = os.path.join(path, page_image)
                sds_image_text += image_to_string(Image.open(_temp_path))

                progress_bar.update((idx/num_pages)*100)

            progress_bar.update(100)
            print()
            return sds_image_text


if __name__ == '__main__':

    def is_requested(arg_requests, file_name):
        for arg_request in arg_requests:
            if file_name.startswith(arg_request):
                return True
        return False

    def get_args(args):
        manufacturer_requests = []
        if args.file_name:
            manufacturer_requests.append(args.file_name)
        for arg in vars(args):
            if getattr(args, arg) is True:
                manufacturer_requests.append(arg)
        return manufacturer_requests

    def generate_args():
        arg_parser = argparse.ArgumentParser(description='select vendors to extract data')
        for manufacturer, _ in SDSRegexes.SDS_FORMAT_REGEXES.items():
            flag = '--' + manufacturer
            arg_parser.add_argument(flag, action='store_true', help=f'extract chemical data from only {manufacturer} SDS files')
        arg_parser.add_argument('-f', '--file_name', type=str, help='extract chemical data from a specific file')
        args = arg_parser.parse_args()
        return args

    sds_parser = SDSParser(debug=True)
    # set arguments
    args = generate_args()
    # get requested manufacturers
    sds_requests = get_args(args)

    with open('chemical_data.csv', 'w') as _:
        writer = csv.writer(_)
        writer.writerow([SDSRegexes.SDS_DATA_TITLES[key] for key in sds_parser.request_keys])

        for file in os.listdir(Configs.SDS_PDF_FILES):
            if sds_requests:
                if not is_requested(sds_requests, file):
                    continue
            file_path = os.path.join(Configs.SDS_PDF_FILES, file)
            chemical_data = sds_parser.get_sds_data(file_path)
            writer.writerow([data for category, data in chemical_data.items()])
