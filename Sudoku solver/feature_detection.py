import os
import cv2

from itertools import product
from numpy import *
from scipy.ndimage import filters, measurements
from skimage import morphology
from PIL import Image, ImageFilter, ImageDraw, ImageFont
from pylab import *
#from pytesseract import image_to_string

from sudoku_grid import SudokuGrid
from svm import SVCPredict
from image_enhancement import LoadImage, Invert, GaussianBlur


#------------------------------------------------------------------------------


def FindContours(im, save_im=False):
    '''
    used for detecting overall grid pattern
    '''
    im = LoadImage(im, grayscale=True)
    ret, thresh = cv2.threshold(im, 127, 255, 0)
    im, contours, hierarchy = cv2.findContours(thresh, cv2.RETR_TREE,
                                               cv2.CHAIN_APPROX_SIMPLE)

    contour_im = cv2.drawContours(im, contours, -1,
                                  (0, 255, 0), 5)

    if save_im == True:
        cv2.imwrite('contours.png', contour_im)

    return contour_im, contours, hierarchy

#------------------------------------------------------------------------------


def MaxApproxContour(all_contours, hierarchy):
    '''
    converts max absolute contour to approximate contour
    '''
    largest_contour = None
    largest_area = 0
    min_area = 50

    # finds top left and bottom right corners through sum of coordinator
    for contour in all_contours:
        area = cv2.contourArea(contour)
        if area > largest_area:
            largest_area = area
            largest_contour = contour

    # sets approximate contour
    epsilon = 0.1 * cv2.arcLength(largest_contour, True)
    appr_contour = cv2.approxPolyDP(largest_contour, epsilon, True)

    if len(appr_contour) != 4:
        # sometimes approxPolyDP detects 5D contour where the 2nd dim
        # is an extra point. Deletes the 2nd dim & reshapes array to
        # ensure detecting square
        appr_contour = delete(appr_contour, 2)
        appr_contour.resize((4, 1, 2))

    assert len(appr_contour) == 4

    points = []
    for i in range(4):
        # following line gives index error for some reason
        points.append((appr_contour[i][0][0], appr_contour[i][0][1]))

    # print(points)
    return points

#------------------------------------------------------------------------------


def DrawRectangle(im, corner_list, save_im=False):
    '''
    overlays rectangle on image given coordinates of corners
    '''
    top_left = None
    bottom_right = None
    minSum = 100000
    maxSum = 0
    for corner in corner_list:
        if corner[0] + corner[1] < minSum:
            minSum = corner[0] + corner[1]
            top_left = corner
        elif corner[0] + corner[1] > maxSum:
            maxSum = corner[0] + corner[1]
            bottom_right = corner
    rect = cv2.rectangle(im, top_left, bottom_right, (0, 0, 255), 8)

    # print('Corner coordinates: (%s %s)' % (top_left, bottom_right))
    if save_im == True:
        cv2.imwrite('rectangle.png', rect)

    return rect, [top_left, bottom_right]

#------------------------------------------------------------------------------


def CropImToRectangle(im, corner_coords, save_im=False):
    '''
    crops image to largest contour detected via. corner coordinates
    '''
    x_min = corner_coords[0][0]
    y_min = corner_coords[0][1]
    x_max = corner_coords[1][0]
    y_max = corner_coords[1][1]

    cropped = im[y_min:y_max, x_min:x_max]
    if save_im == True:
        cv2.imwrite('cropped_rect.png', cropped)

    return cropped

#------------------------------------------------------------------------------


def CropToCenter(im, x_boundary, y_boundary):
    im = asarray(im)
    y, x = im.shape
    y0 = y//2-(y_boundary//2)
    x0 = x//2-(x_boundary//2)
    return im[y0:y0+y_boundary, x0:y0+y_boundary]


#------------------------------------------------------------------------------


def DrawGridOverImg(im, n=9, save_im=False):
    '''
    takes in cropped grid, overlays nxn grid
    '''
    im = LoadImage(im)
    rgb_im = cv2.cvtColor(im, cv2.COLOR_GRAY2RGB)
    width, height = im.shape[:2]
    width_inc = int(width / n)
    height_inc = int(height / n)

    x_col = []
    y_col = []
    # makes list of all endpoints of lines
    for i in range(1, n + 1):
        x_col.append([(width_inc * i, 0), (width_inc * i, height)])
        y_col.append([(0, height_inc * i), (width, height_inc * i)])

    x_arr = asarray(x_col)
    y_arr = asarray(y_col)
    lines = vstack((x_arr, y_arr))  # list of all lines

    polylines = cv2.polylines(rgb_im, lines, False, (0, 0, 255), 8)
    if save_im == True:
        cv2.imwrite('polylines.png', polylines)

    return polylines


#------------------------------------------------------------------------------
def GetSquareImDimensions(im, n):
    # reduces image to square dimensions to prevent out of bounds error
    width, height = im.shape[:2]
    w = int(width / n)
    h = int(height / n)

    if w < h:
        h = w
    else:
        w = h

    return w, h

#------------------------------------------------------------------------------


def OCR(im):
    '''
    pytesseract OCR on single digits. Unclear why doesn't work on test images - use quick & easy SVC instead
    '''
    im = LoadImage(im, grayscale=True)

    # preprocessing - resize, blur, crop to bounding box
    im = cv2.resize(im, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    blur = cv2.blur(im, (5, 5))
    cont_im, cont, hi = FindContours(blur)
    list_corn = MaxApproxContour(cont, hi)
    rect, corners = DrawRectangle(blur, list_corn)
    cropped_rect = Image.fromarray(CropImToRectangle(blur, corners))

    # OCR for 1 char, only detect digits 1-9
    text = image_to_string(
        cropped_rect, config='--psm 10 --oem 3' +
        '-c tessedit_char_whitelist=123456789')

    return text

#------------------------------------------------------------------------------


def OCROnTiles(im, n=9):
    '''
    divides grid into nxn, runs OCR on each, returns SudokuGrid list of
    detected values
    '''
    im = LoadImage(im, grayscale=True)

    w, h = GetSquareImDimensions(im, n)

    starting_board_pos = []  # keeps track of what squares were present @ begin
    flat_grid = SudokuGrid()
    # crops images into individual grid squares, runs OCR on each
    im = Image.fromarray(im)
    for w_i, h_i in product(range(n), repeat=2):
        square = (h_i * h, w_i * w, (h_i + 1) *
                  h, (w_i + 1) * w)
        tile = asarray(im.crop(square))  # crops to one square
        # crops to center of tile
        nx, ny = tile.shape
        center_of_tile = Image.fromarray(CropToCenter(tile, int(90),
                                                      int(90)))
        center_of_tile.save('square%s%s.png' % (w_i, h_i))

        # OCR on square, keep track of initial board state
        num = SVCPredict('square%s%s.png' % (w_i, h_i))
        if num[0] != 0:
            # if value already present, keep track of index
            starting_board_pos.append((w_i, h_i))
        flat_grid.add_value(num[0])

    # delete image files once done running OCR on them
    path = os.getcwd()
    filelist = [f for f in os.listdir(path) if f.endswith('.png')]
    for f in filelist:
        os.remove(os.path.join(path, f))
    return flat_grid, starting_board_pos  # unformatted list of values detected

#------------------------------------------------------------------------------


def SolveOCRGrid(OCR_flat):
    '''
    solves grid provided by OCR detection of postprocessed image

    Input: SudokuGrid flat object
    '''
    grid = OCR_flat.to_grid()
    OCR_flat.solve_grid()
    solved = OCR_flat.display_grid(show=True)

    return solved

#------------------------------------------------------------------------------


def DrawSolvedGrid(im, OCR_flat, starting_board_pos, n=9):
    im = LoadImage(im)
    pil_im = Image.fromarray(im)
    draw = ImageDraw.Draw(pil_im)

    # get list of values for solved grid
    solved_grid = SolveOCRGrid(OCR_flat)
    list_solved_num = [num for row in solved_grid for num in row]

    # if using Windows, will have to change this since Windows has different
    # directories than Linux
    font = ImageFont.truetype(
        "/usr/share/fonts/truetype/freefont/FreeMono.ttf", 40)

    # writes solved puzzle on top of cropped image
    w, h = GetSquareImDimensions(im, n)
    num_idx = 0
    for w_i, h_i in product(range(n), repeat=2):
        num = str(list_solved_num[num_idx])
        # only write new num, not ones in starting state
        if (w_i, h_i) not in starting_board_pos:
            draw.text((h_i*(h) + (45+h/(n/0.5)), w_i*(w) + (45+w/(n/0.5))),
                      num, fill='green', font=font)
        num_idx += 1
    cv2.imwrite('solved.png', np.array(pil_im))


#------------------------------------------------------------------------------


def FindOutline(im):
    '''
    returns outline of grayscale image w/ high background contrast
    '''
    im = LoadImage(im, grayscale=True)
    im = Image.fromarray(im)
    im2 = im.filter(ImageFilter.FIND_EDGES)
    im2.save('outline.png')

#------------------------------------------------------------------------------


def FindOutline_grad(im, filt='Laplacian'):
    '''
    uses gradient filter to detect object outlines. Includes option for
    Sobel filters
    '''
    im = LoadImage(im, grayscale=True)

    if filt == 'sobelx':
        sobelx = cv2.Sobel(im, cv2.CV_64F, 1, 0, ksize=5)
        x_im = Image.fromarray(sobelx).convert('RGB')
        x_im.save('sobelx.png')
        return sobelx
    if filt == 'sobely':
        sobely = cv2.Sobel(im, cv2.CV_64F, 0, 1, ksize=5)
        y_im = Image.fromarray(sobely).convert('RGB')
        y_im.save('sobely.png')
        return sobely
    else:
        lap = cv2.Laplacian(im, cv2.CV_64F)
        lap_im = Image.fromarray(lap).convert('RGB')
        lap_im.save('lap.png')
        return lap

#------------------------------------------------------------------------------


def HoughLineDetection(im):
    im = LoadImage(im)
    gray_im = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    ret, otsu_im = cv2.threshold(
        gray_im, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # inverting & eroding seems to make edge detection work better in most
    # test cases
    otsu_im = 255 - otsu_im

    cv2.imwrite('otsu.png', otsu_im)
    kernel = ones((4, 4), 'uint8')
    eroded = cv2.erode(otsu_im, kernel, iterations=1)

    edges = cv2.Canny(eroded, 150, 200, 3, 5)

    lines = cv2.HoughLines(edges, 1, pi / 180, 500)
    # print(lines)
    for line in lines:
        rho, theta = line[0]
        a = cos(theta)
        b = sin(theta)
        x0 = a * rho
        y0 = b * rho
        x1 = int(x0 + 1000 * (-b))
        y1 = int(y0 + 1000 * (a))
        x2 = int(x0 - 1000 * (-b))
        y2 = int(y0 - 1000 * (a))

        cv2.line(im, (x1, y1), (x2, y2), (0, 0, 255), 2)

    cv2.imwrite('houghlines.png', im)

#------------------------------------------------------------------------------


def PHoughLineDetection(im, threshold=50):
    '''
    lines detection using probabilistic Hough transform
    '''
    im = cv2.imread(im)
    gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    minLineLength = 100
    maxLineGap = 10
    lines = cv2.HoughLinesP(edges, 1, pi / 180,
                            threshold, minLineLength, maxLineGap)

    a, b, c = lines.shape
    for i in range(a):
        cv2.line(im, (lines[i][0][0], lines[i][0][1]), (lines[i][0][2],
                                                        lines[i][0][3]),
                 (0, 0, 255), 3,
                 cv2.LINE_AA)

    cv2.imwrite('Phoughlines.png', im)

#------------------------------------------------------------------------------
